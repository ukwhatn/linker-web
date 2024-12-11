from dataclasses import dataclass


@dataclass
class CustomSchemaBase:
    pass


@dataclass
class SessionAuthSchema(CustomSchemaBase):
    discord_id: int
    code_verifier: str
    code_challenge_method: str
    state: str


@dataclass
class SessionSchema:
    auth: SessionAuthSchema = None
