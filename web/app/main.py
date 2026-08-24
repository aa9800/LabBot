"""LabKeeper 웹 MVP 진입점. 이번 범위는 웹 전용 — 로봇/아두이노 연동은 없음."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import seed
from .routers import api, pages


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed.run()
    yield


app = FastAPI(title="LabKeeper", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(pages.router)
app.include_router(api.router)
