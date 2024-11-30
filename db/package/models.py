from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, DateTime, ForeignKey, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from .connection import Base


class DiscordAccount(Base):
    __tablename__ = "discord_accounts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )
    discord_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True, index=True
    )
    username: Mapped[str] = mapped_column(
        String(255)
    )
    avatar: Mapped[Optional[str]] = mapped_column(
        String(255)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()")
    )

    # Add a relationship to the LinkedAccount model
    linked_accounts: Mapped[list["LinkedAccount"]] = relationship(back_populates="discord")
    link_request_tokens: Mapped[list["LinkRequestToken"]] = relationship(back_populates="discord")


class WikidotAccount(Base):
    __tablename__ = "wikidot_accounts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )
    wikidot_id: Mapped[int] = mapped_column(
        Integer,
        unique=True, index=True
    )
    username: Mapped[str] = mapped_column(
        String(255)
    )
    unixname: Mapped[str] = mapped_column(
        String(255)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()")
    )

    # Add a relationship to the LinkedAccount model
    linked_accounts: Mapped[list["LinkedAccount"]] = relationship(back_populates="wikidot")


class LinkedAccount(Base):
    __tablename__ = "linked_accounts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )
    discord_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("discord_accounts.discord_id", ondelete="CASCADE"),
        index=True
    )
    wikidot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wikidot_accounts.wikidot_id", ondelete="CASCADE"),
        index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()")
    )

    discord: Mapped["DiscordAccount"] = relationship("DiscordAccount")
    wikidot: Mapped["WikidotAccount"] = relationship("WikidotAccount")


class LinkRequestToken(Base):
    __tablename__ = "link_request_tokens"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )
    token: Mapped[str] = mapped_column(
        String(255),
        unique=True
    )
    discord_account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("discord_accounts.id", ondelete="CASCADE"),
        index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()")
    )

    discord: Mapped["DiscordAccount"] = relationship("DiscordAccount")
