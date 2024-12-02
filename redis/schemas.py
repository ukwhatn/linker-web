from dataclasses import dataclass

from db.package.schemas import DiscordAccountSchema


@dataclass
class SessionSchema:
    auth: any = None
