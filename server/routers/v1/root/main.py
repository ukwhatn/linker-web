import base64
import hashlib
import secrets

import httpx
import wikidot
from fastapi import APIRouter, Request, Response, Depends, HTTPException, BackgroundTasks
from fastapi.security import HTTPBearer
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from db.package import schemas as defined_schemas
from db.package.models import WikidotAccount
from db.package.session import db_context, get_db
from db.package.util import IOUtil
from redis_crud.schemas import SessionAuthSchema
from util.env import get_env

# define router
router = APIRouter()

# define bearer scheme
bearer_scheme = HTTPBearer()

templates = Jinja2Templates(directory="templates")

# envs
LINKER_API_KEY = get_env("LINKER_API_KEY", None)
LINKER_SITE_URL = get_env("LINKER_SITE_URL", None)
WD_AUTH_API_URL = get_env("WD_AUTH_API_URL", None)
WD_AUTH_API_CLIENT_ID = get_env("WD_AUTH_API_CLIENT_ID", None)
WD_AUTH_API_CLIENT_SECRET = get_env("WD_AUTH_API_CLIENT_SECRET", None)

if (LINKER_API_KEY is None
        or LINKER_SITE_URL is None
        or WD_AUTH_API_URL is None
        or WD_AUTH_API_CLIENT_ID is None
        or WD_AUTH_API_CLIENT_SECRET is None):
    raise Exception("no environment variable")


def check_api_key(request: Request):
    if LINKER_API_KEY is None:
        return False

    # authorization header
    auth = request.headers.get("Authorization")
    if auth is None:
        return False

    # get bearer token
    auth = auth.split(" ")
    if len(auth) != 2:
        return False

    # check token
    if auth[1] != LINKER_API_KEY:
        return False

    return True


def create_code_challenge(
        code_verifier: str, code_challenge_method: str
) -> str:
    if code_challenge_method == "plain":
        return code_verifier

    elif code_challenge_method == "S256":
        sha256 = hashlib.sha256()
        sha256.update(code_verifier.encode())
        code_verifier_hash = sha256.digest()

        code_challenge_hash = base64.urlsafe_b64encode(code_verifier_hash).decode().rstrip("=")

        return code_challenge_hash

    else:
        raise ValueError("invalid code_challenge_method")


def check_jp_member(db: Session, client: wikidot.Client | None, user: WikidotAccount | int):
    if client is None:
        _client = wikidot.Client()
    else:
        _client = client

    if isinstance(user, int):
        user = IOUtil.get_wikidot_account(db, user)

    result = IOUtil.update_jp_member(db, _client, user)

    if client is None:
        del _client

    return result


def check_jp_member_in_background(user: WikidotAccount | int):
    with get_db() as _db:
        return check_jp_member(_db, None, user)


# define route
@router.post("/start", dependencies=[Depends(bearer_scheme)], response_model=defined_schemas.FlowStartResponseSchema)
async def flow_start(
        request: Request, response: Response,
        req_data: defined_schemas.FlowStartRequestSchema,
        db: Session = Depends(db_context)
):
    if not check_api_key(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # check request data
    token = IOUtil.start_flow(db, req_data.discord)

    if token is None:
        raise HTTPException(status_code=400, detail="Bad Request")

    return defined_schemas.FlowStartResponseSchema(
        url=f"{LINKER_SITE_URL}/v1/auth?token={token}"
    )


@router.get("/auth")
def auth(
        request: Request, response: Response,
        token: str,
        db: Session = Depends(db_context)
):
    discord_acc = IOUtil.get_discord_account_from_token(db, token)
    if discord_acc is None:
        return templates.TemplateResponse("error.html", {
            "error_code": "invalid token",
            "request": request
        }, status_code=400)

    code_verifier = secrets.token_urlsafe(43)
    code_challenge = create_code_challenge(code_verifier, "S256")
    code_challenge_method = "S256"

    request.state.session.auth = SessionAuthSchema(
        discord_id=discord_acc.discord_id,
        code_verifier=code_verifier,
        code_challenge_method=code_challenge_method,
        state=token
    )

    location = (f"{WD_AUTH_API_URL}/authorize"
                f"?response_type=code"
                f"&client_id={WD_AUTH_API_CLIENT_ID}"
                f"&redirect_uri={LINKER_SITE_URL}/v1/callback"
                f"&scope=identify"
                f"&state={token}"
                f"&code_challenge={code_challenge}"
                f"&code_challenge_method={code_challenge_method}")

    response.headers["Location"] = location
    response.status_code = 302

    return response


@router.get("/callback")
def callback(
        request: Request, response: Response,
        code: str, state: str,
        background_tasks: BackgroundTasks,
        db: Session = Depends(db_context)
):
    auth_data = request.state.session.auth
    if auth_data is None:
        return templates.TemplateResponse("error.html", {
            "error_code": "invalid session",
            "request": request
        }, status_code=400)

    if state != auth_data.state:
        request.state.session.auth = None
        return templates.TemplateResponse("error.html", {
            "error_code": "invalid state",
            "request": request
        }, status_code=400)

    code_challenge_method = auth_data.code_challenge_method

    code_verifier = auth_data.code_verifier

    # get info
    userinfo_request = httpx.post(
        f"{WD_AUTH_API_URL}/user",
        json={
            "client_id": WD_AUTH_API_CLIENT_ID,
            "client_secret": WD_AUTH_API_CLIENT_SECRET,
            "code": code,
            "code_verifier": auth_data.code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": f"{LINKER_SITE_URL}/v1/callback"
        })

    if userinfo_request.status_code != 200:
        request.state.session.auth = None
        return templates.TemplateResponse("error.html", {
            "error_code": "invalid token",
            "request": request
        }, status_code=400)

    data = userinfo_request.json()
    wd_user = defined_schemas.WikidotAccountSchema(
        id=data["id"],
        username=data["name"],
        unixname=data["unix_name"]
    )

    discord_account = IOUtil.get_discord_account(db, auth_data.discord_id)
    request.state.session.auth = None

    if discord_account is None:
        return templates.TemplateResponse("error.html", {
            "error_code": "discord id not found",
            "request": request
        }, status_code=400)

    wikidot_account = IOUtil.get_wikidot_account(db, wd_user.id)
    if wikidot_account is None:
        wikidot_account = IOUtil.create_wikidot_account(db, wd_user)

    background_tasks.add_task(check_jp_member_in_background, wikidot_account.wikidot_id)

    link = IOUtil.create_link(db, discord_account, wikidot_account)

    if link is None:
        return templates.TemplateResponse("success.html", {
            "message": "すでにアカウントが連携されています",
            "discord_name": discord_account.username,
            "discord_icon_url": discord_account.avatar,
            "wikidot_name": wikidot_account.username,
            "wikidot_icon_url": "https://www.wikidot.com/avatar.php?userid=" + str(wikidot_account.wikidot_id),
            "request": request
        })

    return templates.TemplateResponse("success.html", {
        "message": "アカウント連携が完了しました",
        "discord_name": discord_account.username,
        "discord_icon_url": discord_account.avatar,
        "wikidot_name": wikidot_account.username,
        "wikidot_icon_url": "https://www.wikidot.com/avatar.php?userid=" + str(wikidot_account.wikidot_id),
        "request": request
    })


@router.post("/recheck", dependencies=[Depends(bearer_scheme)],
             response_model=defined_schemas.FlowRecheckResponseSchema)
async def flow_recheck(
        request: Request, response: Response,
        req_data: defined_schemas.FlowRecheckRequestSchema,
        db: Session = Depends(db_context)
):
    if not check_api_key(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    discord_acc = IOUtil.get_discord_account(db, req_data.discord.id)
    if discord_acc is None:
        raise HTTPException(status_code=404, detail="Not Found")

    # discordアカウント情報更新
    discord_acc = IOUtil.update_discord_account(db, discord_acc, req_data.discord)

    # JPメンバ情報更新
    wikidot_acc = [a.wikidot for a in discord_acc.get_linked_accounts()]

    # 結果格納用
    results = []

    with wikidot.Client() as client:
        for acc in wikidot_acc:
            _acc = check_jp_member(db, client, acc)
            results.append(defined_schemas.AccountResponseWikidotBaseSchema(
                id=_acc.wikidot_id,
                username=_acc.username,
                unixname=_acc.unixname,
                is_jp_member=_acc.is_jp_member
            ))

    return defined_schemas.FlowRecheckResponseSchema(
        discord=defined_schemas.DiscordAccountSchema(
            id=str(discord_acc.discord_id),
            username=discord_acc.username,
            avatar=discord_acc.avatar
        ),
        wikidot=results
    )


@router.post("/list", dependencies=[Depends(bearer_scheme)],
             response_model=defined_schemas.AccountListResponseSchema)
def account_list(
        request: Request, response: Response,
        req_data: defined_schemas.AccountListRequestSchema,
        db: Session = Depends(db_context)
):
    if not check_api_key(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    discord_ids = [int(discord_id) for discord_id in req_data.discord_ids]
    discord_accounts = IOUtil.get_some_discord_accounts(db, discord_ids)

    results = [defined_schemas.AccountResponseFromDiscordSchema(
        discord=defined_schemas.DiscordAccountSchema(
            id=str(discord_acc.discord_id),
            username=discord_acc.username,
            avatar=discord_acc.avatar
        ),
        wikidot=[defined_schemas.AccountResponseWikidotBaseSchema(
            id=a.wikidot.wikidot_id,
            username=a.wikidot.username,
            unixname=a.wikidot.unixname,
            is_jp_member=a.wikidot.is_jp_member
        ) for a in discord_acc.get_linked_accounts()]
    ) for discord_acc in discord_accounts]

    return defined_schemas.AccountListResponseSchema(
        result={r.discord.id: r for r in results}
    )


@router.get("/list/discord", dependencies=[Depends(bearer_scheme)],
            response_model=defined_schemas.ListDiscordResponseSchema)
def discord_account_list(
        request: Request, response: Response,
        db: Session = Depends(db_context)
):
    if not check_api_key(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    discord_accounts = IOUtil.get_discord_accounts(db)

    result = []

    for acc in discord_accounts:
        result.append(defined_schemas.ListDiscordItemSchema(
            discord=defined_schemas.DiscordAccountSchema(
                id=str(acc.discord_id),
                username=acc.username,
                avatar=acc.avatar
            ),
            wikidot=[defined_schemas.WikidotAccountSchemaForManage(
                id=a.wikidot.wikidot_id,
                username=a.wikidot.username,
                unixname=a.wikidot.unixname,
                is_jp_member=a.wikidot.is_jp_member,
                unlinked_at=a.unlinked_at,
                created_at=a.created_at,
                updated_at=a.updated_at
            ) for a in acc.get_linked_accounts(include_unlinked=True)]
        ))

    return defined_schemas.ListDiscordResponseSchema(
        result=result
    )


@router.get("/list/wikidot", dependencies=[Depends(bearer_scheme)],
            response_model=defined_schemas.ListWikidotResponseSchema)
def wikidot_account_list(
        request: Request, response: Response,
        db: Session = Depends(db_context)
):
    if not check_api_key(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    wikidot_accounts = IOUtil.get_wikidot_accounts(db)

    result = []

    for acc in wikidot_accounts:
        result.append(defined_schemas.ListWikidotItemSchema(
            discord=[defined_schemas.DiscordAccountSchemaForManage(
                id=str(a.discord.discord_id),
                username=a.discord.username,
                avatar=a.discord.avatar,
                unlinked_at=a.unlinked_at,
                created_at=a.created_at,
                updated_at=a.updated_at
            ) for a in acc.get_linked_accounts(include_unlinked=True)],
            wikidot=defined_schemas.AccountResponseWikidotBaseSchema(
                id=acc.wikidot_id,
                username=acc.username,
                unixname=acc.unixname,
                is_jp_member=acc.is_jp_member
            )
        ))

    return defined_schemas.ListWikidotResponseSchema(
        result=result
    )


@router.patch("/unlink", dependencies=[Depends(bearer_scheme)])
def unlink(
        request: Request, response: Response,
        discord_id: int, wikidot_id: int,
        db: Session = Depends(db_context)
):
    if not check_api_key(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = IOUtil.unlink(db, discord_id, wikidot_id)

    return defined_schemas.UnlinkResponseSchema(
        result=result
    )


@router.patch("/relink", dependencies=[Depends(bearer_scheme)])
def relink(
        request: Request, response: Response,
        discord_id: int, wikidot_id: int,
        db: Session = Depends(db_context)
):
    if not check_api_key(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = IOUtil.relink(db, discord_id, wikidot_id)

    return defined_schemas.RelinkResponseSchema(
        result=result
    )
