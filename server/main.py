import json
import logging

import sentry_sdk
from fastapi import FastAPI, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware

from db.package.session import get_db
from redis_crud import SessionCrud
from redis_crud.schemas import SessionSchema
from routers.system import main as system_router
from routers.v1 import main as v1_router
from util.env import get_env

# get environment mode
env_mode = get_env("ENV_MODE", "production")

# logger config
logging.basicConfig(level=logging.WARN)
logger = logging.getLogger("uvicorn")

# sentry
SENTRY_DSN = get_env("SENTRY_DSN", None)
if SENTRY_DSN is not None:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=1.0,
        _experiments={
            "continuous_profiling_auto_start": True,
        },
    )


# /system/healthcheckのログを表示しない
class HealthCheckFilter(logging.Filter):
    def filter(self, record):
        return "/system/healthcheck" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())

# production時，docsを表示しない
app_params = {}
if env_mode == "development":
    logger.setLevel(level=logging.DEBUG)
elif env_mode == "production":
    logger.setLevel(level=logging.INFO)
    app_params["docs_url"] = None
    app_params["redoc_url"] = None
    app_params["openapi_url"] = None

# create app
app = FastAPI(**app_params)

origins = ["https://scp-jp.github.io", "https://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if env_mode == "development" else origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
def error_response(request: Request, call_next):
    response = Response(
        json.dumps({"status": "internal server error"}), status_code=500
    )
    try:
        response = call_next(request)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(e)
    return response


@app.middleware("http")
async def db_opener(request: Request, call_next, db=Depends(get_db)):
    request.state.db = db
    return await call_next(request)


@app.middleware("http")
async def session_creator(request: Request, call_next):
    with SessionCrud() as session_crud:
        req_session_data = session_crud.get(request)
        if req_session_data is None:
            req_session_data = SessionSchema()
        request.state.session = req_session_data
        print(req_session_data)

    response = await call_next(request)

    with SessionCrud() as session_crud:
        res_session_data = request.state.session
        session_crud.update(request, response, res_session_data)
        print(res_session_data)
    return response


# mount static folder
# app.mount("/static", StaticFiles(directory="/app/static"), name="static")

# add routers
app.include_router(v1_router.router, prefix="/v1")

app.include_router(system_router.router, prefix="/system")
