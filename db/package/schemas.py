from pydantic import BaseModel


class DiscordAccountSchema(BaseModel):
    """Discordアカウントのスキーマ"""
    id: int
    username: str
    avatar: str


class WikidotAccountSchema(BaseModel):
    """Wikidotアカウントのスキーマ"""
    id: int
    username: str
    unixname: str


class FlowStartRequestSchema(BaseModel):
    """FlowStartのリクエスト"""
    discord: DiscordAccountSchema


class FlowStartResponseSchema(BaseModel):
    """FlowStartのレスポンス"""
    url: str
