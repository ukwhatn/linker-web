import secrets
from datetime import datetime, timedelta

import wikidot
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from . import schemas
from .models import DiscordAccount, WikidotAccount, LinkedAccount, LinkRequestToken


class IOUtil:
    @staticmethod
    def get_discord_account(db: Session, discord_id: int) -> DiscordAccount | None:
        return db.execute(
            select(DiscordAccount)
            .options(
                joinedload(DiscordAccount.linked_accounts)
                .joinedload(LinkedAccount.wikidot)
            )
            .where(DiscordAccount.discord_id == discord_id)
        ).scalars().first()

    @staticmethod
    def create_discord_account(db: Session, acc: schemas.DiscordAccountSchema) -> DiscordAccount:
        discord = DiscordAccount(
            discord_id=acc.id,
            username=acc.username,
            avatar=acc.avatar
        )
        db.add(discord)
        db.commit()
        db.refresh(discord)
        return discord

    @staticmethod
    def update_discord_account(db: Session, acc: DiscordAccount,
                               new_data: schemas.DiscordAccountSchema) -> DiscordAccount:
        acc.username = new_data.username
        acc.avatar = new_data.avatar
        db.commit()
        db.refresh(acc)
        return acc

    @staticmethod
    def get_wikidot_account(db: Session, wikidot_id: int) -> WikidotAccount | None:
        return db.execute(
            select(WikidotAccount)
            .options(
                joinedload(WikidotAccount.linked_accounts)
                .joinedload(LinkedAccount.discord)
            )
            .where(WikidotAccount.wikidot_id == wikidot_id)
        ).scalars().first()

    @staticmethod
    def create_wikidot_account(db: Session, acc: schemas.WikidotAccountSchema) -> WikidotAccount:
        wd_acc = WikidotAccount(
            wikidot_id=acc.id,
            username=acc.username,
            unixname=acc.unixname
        )
        db.add(wd_acc)
        db.commit()
        db.refresh(wd_acc)
        return wd_acc

    @staticmethod
    def create_link(db: Session, dc_acc: DiscordAccount, wd_acc: WikidotAccount) -> LinkedAccount | None:
        # 存在チェック
        link = db.execute(select(LinkedAccount).where(
            LinkedAccount.discord_id == dc_acc.discord_id,
            LinkedAccount.wikidot_id == wd_acc.wikidot_id
        )).scalars().first()
        if link is not None:
            if link.unlinked_at is None:
                return None
            link.unlinked_at = None
            db.commit()
            db.refresh(link)
            return link

        link = LinkedAccount(
            discord=dc_acc,
            wikidot=wd_acc
        )
        db.add(link)
        db.commit()
        db.refresh(link)
        return link

    @staticmethod
    def get_discord_account_from_token(db: Session, token: str) -> DiscordAccount | None:
        # 10分以内のトークンを取得
        token = db.execute(select(LinkRequestToken).where(
            LinkRequestToken.token == token,
            LinkRequestToken.created_at >= datetime.now() - timedelta(minutes=10)
        )).scalars().first()
        if token is None:
            return None

        return token.discord

    @staticmethod
    def start_flow(db: Session, acc: schemas.DiscordAccountSchema) -> LinkRequestToken:
        print(acc)
        discord_account = IOUtil.get_discord_account(db, int(acc.id))
        if discord_account is None:
            discord_account = IOUtil.create_discord_account(db, acc)

        token = LinkRequestToken(
            discord=discord_account,
            token=secrets.token_urlsafe(32),
            created_at=datetime.now()
        )
        db.add(token)
        db.commit()

        return token.token

    @staticmethod
    def update_jp_member(db: Session, client: wikidot.Client, user: WikidotAccount) -> WikidotAccount:
        site = client.site.get("scp-jp")
        user.is_jp_member = site.member_lookup(user.username, user.wikidot_id)
        db.commit()
        db.refresh(user)

        return user

    @staticmethod
    def get_discord_accounts(db: Session):
        return db.execute(
            select(DiscordAccount)
            .options(
                joinedload(DiscordAccount.linked_accounts)
                .joinedload(LinkedAccount.wikidot)
            )
        ).scalars().all()

    @staticmethod
    def get_wikidot_accounts(db: Session):
        return db.execute(
            select(WikidotAccount)
            .options(
                joinedload(WikidotAccount.linked_accounts)
                .joinedload(LinkedAccount.discord)
            )
        ).scalars().all()

    @staticmethod
    def unlink(db: Session, discord_id: int, wikidot_id: int):
        target = db.execute(select(LinkedAccount).where(
            LinkedAccount.discord_id == discord_id,
            LinkedAccount.wikidot_id == wikidot_id
        )).scalars().first()

        if target is None:
            return False

        target.unlinked_at = datetime.now()
        db.commit()
        return True

    @staticmethod
    def relink(db: Session, discord_id: int, wikidot_id: int):
        target = db.execute(select(LinkedAccount).where(
            LinkedAccount.discord_id == discord_id,
            LinkedAccount.wikidot_id == wikidot_id,
            LinkedAccount.unlinked_at != None
        )).scalars().first()

        if target is None:
            return False

        target.unlinked_at = None
        db.commit()
        return True
