from pydantic import BaseModel


class DiscordAccountSchema(BaseModel):
    """Discordアカウントのスキーマ"""
    id: str
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


class AccountResponseWikidotBaseSchema(WikidotAccountSchema):
    """Botにレスポンスとして渡すためのWikidotアカウント情報のスキーマ"""
    is_jp_member: bool


class AccountResponseFromDiscordSchema(BaseModel):
    """Discord IDを主語として、関連するアカウント情報を返す"""
    discord: DiscordAccountSchema
    wikidot: list[AccountResponseWikidotBaseSchema]


class AccountResponseFromWikidotSchema(BaseModel):
    """Wikidot IDを主語として、関連するアカウント情報を返す"""
    discord: list[DiscordAccountSchema]
    wikidot: AccountResponseWikidotBaseSchema


class FlowRecheckRequestSchema(BaseModel):
    """FlowRecheckのリクエスト"""
    discord: DiscordAccountSchema


class FlowRecheckResponseSchema(AccountResponseFromDiscordSchema):
    """FlowRecheckのレスポンス"""
    pass


class AccountListRequestSchema(BaseModel):
    """AccountCheckのリクエスト"""
    discord_ids: list[str]


class AccountListResponseSchema(BaseModel):
    """AccountCheckのレスポンス"""
    result: dict[str, AccountResponseFromDiscordSchema]


class DiscordAccountListSchema(BaseModel):
    """Discordアカウントのリスト"""
    result: list[AccountResponseFromDiscordSchema]


class WikidotAccountListSchema(BaseModel):
    """Wikidotアカウントのリスト"""
    result: list[AccountResponseFromWikidotSchema]


class UnlinkRequestSchema(BaseModel):
    """Unlinkのリクエスト"""
    discord: DiscordAccountSchema
    wikidot: WikidotAccountSchema


class UnlinkResponseSchema(BaseModel):
    """Unlinkのレスポンス"""
    result: bool
