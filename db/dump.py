import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from typing import List, Tuple

import boto3
import schedule
import sentry_sdk
from botocore.exceptions import ClientError
from pick import pick

# S3設定
S3_ENDPOINT = os.environ['S3_ENDPOINT']
S3_ACCESS_KEY = os.environ['S3_ACCESS_KEY']
S3_SECRET_KEY = os.environ['S3_SECRET_KEY']
S3_BUCKET = os.environ['S3_BUCKET']
BACKUP_DIR = os.environ.get('BACKUP_DIR', 'default')

# ライフサイクル設定
BACKUP_RETENTION_DAYS = int(os.environ.get('BACKUP_RETENTION_DAYS', 30))
BACKUP_TIME = os.environ.get('BACKUP_TIME', '03:00')

# データベース設定
DB_HOST = os.environ['POSTGRES_HOST']
DB_NAME = os.environ['POSTGRES_DB']
DB_USER = os.environ['POSTGRES_USER']
DB_PASSWORD = os.environ['POSTGRES_PASSWORD']

# ロガー
LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Sentry
SENTRY_DSN = os.environ.get('SENTRY_DSN', None)
if SENTRY_DSN is not None:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=1.0
    )


def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY
    )


def ensure_backup_directory(s3_client):
    """バックアップディレクトリの存在確認と作成"""
    try:
        # ディレクトリの存在確認
        s3_client.head_object(Bucket=S3_BUCKET, Key=f'{BACKUP_DIR}/')
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            # ディレクトリが存在しない場合、空のオブジェクトを作成してディレクトリとする
            try:
                s3_client.put_object(Bucket=S3_BUCKET, Key=f'{BACKUP_DIR}/')
                LOGGER.info(f"Created backup directory: {BACKUP_DIR}/")
            except Exception as create_error:
                sentry_sdk.capture_exception(create_error)
                LOGGER.error(f"Error creating backup directory: {str(create_error)}")
                raise
        else:
            sentry_sdk.capture_exception(e)
            LOGGER.error(f"Error checking backup directory: {str(e)}")
            raise


def get_backup_files(s3_client) -> List[Tuple[str, datetime]]:
    """バックアップファイルの一覧を取得"""
    backup_files = []

    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=f'{BACKUP_DIR}/backup_'):
            if 'Contents' not in page:
                continue

            for obj in page['Contents']:
                try:
                    filename = obj['Key']
                    if not filename.startswith(f'{BACKUP_DIR}/backup_'):
                        continue

                    date_str = filename.split('_')[1]
                    time_str = filename.split('_')[2].split('.')[0]
                    dt = datetime.strptime(f"{date_str}_{time_str}", '%Y%m%d_%H%M%S')
                    backup_files.append((filename, dt))
                except (IndexError, ValueError) as e:
                    sentry_sdk.capture_exception(e)
                    LOGGER.error(f"Warning: Could not parse date from filename: {filename}")
                    continue

    except Exception as e:
        sentry_sdk.capture_exception(e)
        LOGGER.error(f"Error listing backup files: {str(e)}")

    # 日付の新しい順にソート
    return sorted(backup_files, key=lambda x: x[1], reverse=True)


def list_old_backups(s3_client) -> List[str]:
    """指定した日数より古いバックアップを一覧取得"""
    cutoff_date = datetime.now() - timedelta(days=BACKUP_RETENTION_DAYS)
    old_backups = []

    try:
        # 指定されたディレクトリ内のオブジェクトを取得
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=f'{BACKUP_DIR}/backup_'):
            if 'Contents' not in page:
                continue

            for obj in page['Contents']:
                filename = ''
                try:
                    filename = obj['Key']
                    # バックアップファイルのみを対象とする
                    if not filename.startswith(f'{BACKUP_DIR}/backup_'):
                        continue

                    date_str = filename.split('_')[1]
                    file_date = datetime.strptime(date_str, '%Y%m%d')

                    if file_date < cutoff_date:
                        old_backups.append(filename)
                except (IndexError, ValueError) as e:
                    sentry_sdk.capture_exception(e)
                    LOGGER.error(f"Warning: Could not parse date from filename: {filename}")
                    continue

    except Exception as e:
        sentry_sdk.capture_exception(e)
        LOGGER.error(f"Error listing old backups: {str(e)}")

    return old_backups


def delete_old_backups(s3_client, old_backups: List[str]):
    """古いバックアップを削除"""
    if not old_backups:
        return

    try:
        objects_to_delete = [{'Key': key} for key in old_backups]
        s3_client.delete_objects(
            Bucket=S3_BUCKET,
            Delete={'Objects': objects_to_delete}
        )
        LOGGER.info(f"Deleted {len(old_backups)} old backup(s) from {BACKUP_DIR}/")
    except Exception as e:
        sentry_sdk.capture_exception(e)
        LOGGER.error(f"Error deleting old backups: {str(e)}")


def restore_backup(backup_key: str):
    """バックアップをレストア"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_file = f'/tmp/restore_{timestamp}.sql'

    try:
        # S3からファイルをダウンロード
        s3_client = get_s3_client()
        s3_client.download_file(
            S3_BUCKET,
            backup_key,
            temp_file
        )

        LOGGER.info(f"Downloaded backup file: {backup_key}")

        # pg_restoreを実行
        try:
            # 既存の接続を切断
            disconnect_cmd = f"""
            SELECT pg_terminate_backend(pid) 
            FROM pg_stat_activity 
            WHERE datname = '{DB_NAME}'
            AND pid <> pg_backend_pid();
            """

            subprocess.run([
                'psql',
                f'--host={DB_HOST}',
                f'--dbname=postgres',  # postgresデータベースに接続
                f'--username={DB_USER}',
                '-c', disconnect_cmd
            ], env={'PGPASSWORD': DB_PASSWORD}, check=True, capture_output=True, text=True)

            # データベースを再作成
            subprocess.run([
                'dropdb',
                f'--host={DB_HOST}',
                f'--username={DB_USER}',
                '--if-exists',
                DB_NAME
            ], env={'PGPASSWORD': DB_PASSWORD}, check=True, capture_output=True, text=True)

            subprocess.run([
                'createdb',
                f'--host={DB_HOST}',
                f'--username={DB_USER}',
                DB_NAME
            ], env={'PGPASSWORD': DB_PASSWORD}, check=True, capture_output=True, text=True)

            # レストア実行
            run = subprocess.run([
                'psql',
                f'--host={DB_HOST}',
                f'--dbname={DB_NAME}',
                f'--username={DB_USER}',
                '-f', temp_file
            ], env={'PGPASSWORD': DB_PASSWORD}, check=True, capture_output=True, text=True)

            LOGGER.info(f"Restore completed successfully")
            LOGGER.debug(run.stdout)

        except subprocess.CalledProcessError as e:
            sentry_sdk.capture_exception(e)
            LOGGER.error(f'Error during restore: {e.stderr}')
            LOGGER.error(f'Restore output: {e.stdout}')
            raise e

    except Exception as e:
        sentry_sdk.capture_exception(e)
        LOGGER.error(f'Restore failed: {str(e)}')
    finally:
        # 一時ファイルを削除
        if os.path.exists(temp_file):
            os.remove(temp_file)


def create_backup():
    """バックアップを作成してS3にアップロード"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = f'/tmp/backup_{timestamp}.sql'

    try:
        # pg_dumpを実行（データのみ）
        try:
            run = subprocess.run([
                'pg_dump',
                f'--host={DB_HOST}',
                f'--dbname={DB_NAME}',
                f'--username={DB_USER}',
                '--format=plain',
                f'--file={backup_file}'
            ], env={'PGPASSWORD': DB_PASSWORD}, check=True, capture_output=True, text=True)
            LOGGER.info(run.stdout)
        except subprocess.CalledProcessError as e:
            sentry_sdk.capture_exception(e)
            LOGGER.error(f'Error running pg_dump: {e.stderr}')
            LOGGER.error(f'pg_dump output: {e.stdout}')
            raise e

        # S3クライアントの初期化
        s3_client = get_s3_client()

        # バックアップディレクトリの確認/作成
        ensure_backup_directory(s3_client)

        # S3にアップロード
        s3_key = f'{BACKUP_DIR}/backup_{timestamp}.sql'
        s3_client.upload_file(
            backup_file,
            S3_BUCKET,
            s3_key
        )

        LOGGER.info(f'Backup completed successfully: {s3_key}')

        # 古いバックアップの削除
        old_backups = list_old_backups(s3_client)
        if old_backups:
            delete_old_backups(s3_client, old_backups)

        # 一時ファイルを削除
        os.remove(backup_file)

    except Exception as e:
        sentry_sdk.capture_exception(e)
        LOGGER.error(f'Backup failed: {str(e)}')


def main():
    LOGGER.info(f"Starting backup service for directory: {BACKUP_DIR}/")

    # コマンドライン引数の取得
    arg1 = sys.argv[1] if len(sys.argv) > 1 else None

    if arg1 == "oneshot":
        LOGGER.info(f"Running oneshot backup")
        create_backup()
        return
    elif arg1 == "restore":
        LOGGER.info("Starting restore process")
        s3_client = get_s3_client()
        backup_files = get_backup_files(s3_client)

        if not backup_files:
            LOGGER.error("No backup files found")
            return

        # バックアップファイルの選択
        title = 'Please select a backup file to restore:'
        options = [f"{dt.strftime('%Y-%m-%d %H:%M:%S')} - {key}" for key, dt in backup_files]
        option, index = pick(options, title)

        # 選択されたファイルのレストア
        selected_key = backup_files[index][0]
        LOGGER.info(f"Selected backup file: {selected_key}")

        # 確認
        confirm_title = f'Are you sure you want to restore {selected_key}? This will DELETE ALL EXISTING DATA!'
        confirm_options = ['Yes', 'No']
        confirm_option, _ = pick(confirm_options, confirm_title)

        if confirm_option == 'Yes':
            create_backup()
            restore_backup(selected_key)
        else:
            LOGGER.info("Restore cancelled")
        return
    else:
        LOGGER.info(f"Retention period: {BACKUP_RETENTION_DAYS} days")
        LOGGER.info(f"Scheduled backup time: {BACKUP_TIME}")

        schedule.every().day.at(BACKUP_TIME).do(create_backup)

        while True:
            schedule.run_pending()
            time.sleep(30)


if __name__ == "__main__":
    main()