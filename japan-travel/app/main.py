from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.analytics import track_page_view
from app.config import get_settings
from app.db import init_db
from app.routers import admin, api, auth, pages, payments

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    https_only=settings.base_url.startswith("https://"),
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(pages.router, dependencies=[Depends(track_page_view)])
app.include_router(auth.router)
app.include_router(api.router)
app.include_router(payments.router)
app.include_router(admin.router)
