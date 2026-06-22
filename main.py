from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

os.environ.setdefault("TZ", "Asia/Karachi")

# Load environment variables before any settings import (project root .env, then cwd).
_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")
load_dotenv()

import uvicorn

from app.config import get_settings
from app.main import app


if __name__ == "__main__":
    """
    Application entrypoint when running `python main.py`.

    This uses the configured host/port from `Settings` so you have a single
    source of truth for how the API is exposed.
    """

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.environment == "development",
    )
