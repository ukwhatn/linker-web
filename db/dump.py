import logging
import os
import subprocess
import time
from datetime import datetime, timedelta
from typing import List

import boto3
import schedule
from botocore.exceptions import ClientError

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
                LOGGER.info(f"Error creating backup directory: {str(create_error)}")
                raise
        else:
            LOGGER.info(f"Error checking backup directory: {str(e)}")
            raise


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
                try:
                    filename = obj['Key']
                    # バックアップファイルのみを対象とする
                    if not filename.startswith(f'{BACKUP_DIR}/backup_'):
                        continue

                    date_str = filename.split('_')[1]
                    file_date = datetime.strptime(date_str, '%Y%m%d')

                    if file_date < cutoff_date:
                        old_backups.append(filename)
                except (IndexError, ValueError):
                    LOGGER.info(f"Warning: Could not parse date from filename: {filename}")
                    continue

    except Exception as e:
        LOGGER.info(f"Error listing old backups: {str(e)}")

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
        LOGGER.info(f"Error deleting old backups: {str(e)}")


def create_backup():
    """バックアップを作成してS3にアップロード"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = f'/tmp/backup_{timestamp}.sql'

    try:
        # pg_dumpを実行
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
            LOGGER.info(f'Error running pg_dump: {e.stderr}')
            LOGGER.info(f'pg_dump output: {e.stdout}')
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
        LOGGER.info(f'Backup failed: {str(e)}')


def main():
    LOGGER.info(f"Starting backup service for directory: {BACKUP_DIR}/")
    LOGGER.info(f"Retention period: {BACKUP_RETENTION_DAYS} days")
    LOGGER.info(f"Scheduled backup time: {BACKUP_TIME}")

    # 指定された時刻にバックアップを実行
    schedule.every().day.at(BACKUP_TIME).do(create_backup)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()