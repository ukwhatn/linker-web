import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import schemas
from .models import DiscordAccount, WikidotAccount, LinkedAccount, LinkRequestToken


class IOUtil:
    @staticmethod
    def get_discord_account(db: Session, discord_id: int) -> DiscordAccount | None:
        return db.execute(select(DiscordAccount).where(DiscordAccount.discord_id == discord_id)).scalars().first()

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
    def get_wikidot_account(db: Session, wikidot_id: int) -> WikidotAccount | None:
        return db.execute(select(WikidotAccount).where(WikidotAccount.wikidot_id == wikidot_id)).scalars().first()

    @staticmethod
    def create_wikidot_account(db: Session, acc: schemas.WikidotAccountSchema) -> WikidotAccount:
        wikidot = WikidotAccount(
            wikidot_id=acc.id,
            username=acc.username,
            unixname=acc.unixname
        )
        db.add(wikidot)
        db.commit()
        db.refresh(wikidot)
        return wikidot

    @staticmethod
    def create_link(db: Session, discord: DiscordAccount, wikidot: WikidotAccount) -> LinkedAccount:
        # 存在チェック
        link = db.execute(select(LinkedAccount).where(
            LinkedAccount.discord_id == discord.discord_id,
            LinkedAccount.wikidot_id == wikidot.wikidot_id
        )).scalars().first()
        if link is not None:
            return None

        link = LinkedAccount(
            discord=discord,
            wikidot=wikidot
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
        discord_account = IOUtil.get_discord_account(db, acc.id)
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
