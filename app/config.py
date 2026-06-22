from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Default process timezone (Pakistan). Affects some stdlib time APIs on Unix/macOS.
# Datetimes are still stored and exposed as UTC where possible; see UtcTimestampMixin.
os.environ.setdefault("TZ", "Asia/Karachi")
from pydantic import SecretStr
from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve project root (parent of app/) and load .env before Settings is instantiated.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DOTENV_PATH = _PROJECT_ROOT / ".env"
load_dotenv(_DOTENV_PATH)
load_dotenv(Path(".env"))

# Pydantic Settings also reads env_file (same path when present).
_ENV_FILE_FOR_SETTINGS: str | Path = str(_DOTENV_PATH) if _DOTENV_PATH.is_file() else ".env"


class Settings(BaseSettings):
    """
    Centralized application configuration.

    - Values can be provided via environment variables or a `.env` file in the project root.
    - Keep secrets out of source control; use `.env` (not committed) in development.
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE_FOR_SETTINGS,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="QuickStudy LMS", alias="APP_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")

    api_prefix: str = Field(default="/quickstudy", alias="API_PREFIX")

    # Network configuration
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8001, alias="API_PORT")

    # Database configuration
    sqlite_path: str = Field(default="quickstudy.db", alias="SQLITE_PATH")

    # Security / Auth configuration
    jwt_secret_key: SecretStr = Field(default=SecretStr("CHANGE_ME"), alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=60, alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    # Uploads
    uploads_dir: Path = Field(default=Path("uploads"), alias="UPLOADS_DIR")
    max_upload_size_mb: int = Field(default=500, alias="MAX_UPLOAD_SIZE_MB")

    # OpenAI Whisper API (audio transcriptions)
    whisper_api_model: str = Field(default="whisper-1", alias="WHISPER_API_MODEL")
    whisper_word_probability_min: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        alias="WHISPER_WORD_PROBABILITY_MIN",
    )

    # OpenAI (transcript cleaning + summary + optional polish). Required for transcript and summary pipelines.
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    huggingface_api_token: SecretStr | None = Field(default=None, alias="HUGGINGFACE_API_TOKEN")
    hf_refinement_model: str = Field(
        default="Qwen/Qwen2.5-1.5B-Instruct",
        alias="HF_REFINEMENT_MODEL",
    )

    # CORS configuration
    backend_cors_origins: list[AnyHttpUrl] = Field(default_factory=list, alias="BACKEND_CORS_ORIGINS")

    # Display / server locale (IANA name). Does not change API contract: prefer UTC in JSON.
    app_timezone: str = Field(default="Asia/Karachi", alias="APP_TIMEZONE")


_settings: Settings | None = None


def get_settings() -> Settings:
    """
    Cached settings getter to avoid re-parsing environment on every import.
    """

    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
