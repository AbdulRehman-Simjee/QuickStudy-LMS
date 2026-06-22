from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

os.environ.setdefault("TZ", "Asia/Karachi")

# Ensure .env is loaded when the app is started via `uvicorn app.main:app` (not only via root main.py).
_APP_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _APP_DIR.parent
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv()

from app.core.logger import setup_logging

setup_logging()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.routes.auth import router as auth_router
from app.routes.audio import router as audio_router
from app.routes.quickstudy import router as quickstudy_router
from app.routes.transcripts import router as transcripts_router
from app.routes.videos import router as videos_router
from app.routes.summaries import router as summaries_router
from app.routes.quiz import router as quiz_router
from app.routes.assessment import router as assessment_router
from app.routes.chat import router as chat_router
from app.routes.progress import router as progress_router
from app.routes.dashboard import router as dashboard_router
from app.routes.results import router as results_router
from app.routes.downloads import router as downloads_router
from app.routes.teacher import router as teacher_router
from app.routes.billing import router as billing_router
from app.routes.settings import router as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan hook.

    Use this for:
    - database initialization (migrations are preferred over create_all in production)
    - loading ML models / clients
    - warm caches / startup checks
    """

    init_db()

    # Ensure upload directories exist.
    settings = get_settings()
    (settings.uploads_dir / "videos").mkdir(parents=True, exist_ok=True)
    (settings.uploads_dir / "audio").mkdir(parents=True, exist_ok=True)
    (settings.uploads_dir / "avatars").mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(parents=True, exist_ok=True)
    yield


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)
app.mount("/uploads", StaticFiles(directory=str(settings.uploads_dir)), name="uploads")

# CORS must always be registered for browser preflight (OPTIONS). Previously it was skipped when
# BACKEND_CORS_ORIGINS was empty, which caused 405 on OPTIONS (e.g. Vite on localhost:5173).
_cors_origins: list[str] = []
for url in settings.backend_cors_origins:
    s = str(url).rstrip("/")
    if s and s not in _cors_origins:
        _cors_origins.append(s)
if "http://localhost:5173" not in _cors_origins:
    _cors_origins.append("http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)

# Routes
app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(quickstudy_router, prefix=settings.api_prefix)
app.include_router(videos_router)
app.include_router(audio_router)
app.include_router(transcripts_router)
app.include_router(summaries_router)
app.include_router(quiz_router)
app.include_router(assessment_router)
app.include_router(chat_router)
app.include_router(chat_router, prefix=settings.api_prefix)
app.include_router(progress_router)
app.include_router(dashboard_router)
app.include_router(results_router)
app.include_router(downloads_router)
app.include_router(teacher_router)
app.include_router(billing_router)

