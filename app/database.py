from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

# Timestamps: SQLite CURRENT_TIMESTAMP is UTC; Pydantic schemas coerce naive values to UTC for JSON.


class Base(DeclarativeBase):
    """
    Base class for SQLAlchemy ORM models.
    """


def _build_sqlite_url(sqlite_path: str) -> str:
    # For SQLite, a relative path is resolved relative to the process working directory.
    # In production, prefer an absolute path (or move to Postgres/MySQL).
    return f"sqlite+pysqlite:///{sqlite_path}"


settings = get_settings()

engine = create_engine(
    _build_sqlite_url(settings.sqlite_path),
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)


def init_db() -> None:
    """
    Initialize database schema.

    Notes:
    - For production systems, prefer migrations (e.g., Alembic) over `create_all`.
    - For this FYP scaffold, `create_all` provides a simple, reliable starting point.
    """

    # Import models so SQLAlchemy registers them on `Base.metadata`.
    # This avoids a common footgun where tables are never created because models
    # weren't imported anywhere.
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_users_plan_column()
    _ensure_users_avatar_url_column()
    _ensure_users_pro_expires_at_column()
    _ensure_videos_youtube_cache_columns()


def _ensure_users_plan_column() -> None:
    """
    Lightweight migration for legacy SQLite databases: add users.plan if missing.
    """

    with engine.begin() as conn:
        cols = conn.exec_driver_sql("PRAGMA table_info(users);").fetchall()
        col_names = {row[1] for row in cols}
        if "plan" not in col_names:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN plan VARCHAR(20) NOT NULL DEFAULT 'free';")


def _ensure_users_avatar_url_column() -> None:
    """Add users.avatar_url for legacy SQLite databases."""

    with engine.begin() as conn:
        cols = conn.exec_driver_sql("PRAGMA table_info(users);").fetchall()
        col_names = {row[1] for row in cols}
        if "avatar_url" not in col_names:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(500);")


def _ensure_users_pro_expires_at_column() -> None:
    with engine.begin() as conn:
        cols = conn.exec_driver_sql("PRAGMA table_info(users);").fetchall()
        col_names = {row[1] for row in cols}
        if "pro_expires_at" not in col_names:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN pro_expires_at DATETIME;")


def _ensure_videos_youtube_cache_columns() -> None:
    with engine.begin() as conn:
        cols = conn.exec_driver_sql("PRAGMA table_info(videos);").fetchall()
        col_names = {row[1] for row in cols}
        if "youtube_url" not in col_names:
            conn.exec_driver_sql("ALTER TABLE videos ADD COLUMN youtube_url VARCHAR(512);")
        if "transcript_status" not in col_names:
            conn.exec_driver_sql(
                "ALTER TABLE videos ADD COLUMN transcript_status VARCHAR(20) NOT NULL DEFAULT 'pending';",
            )
        if "summary_status" not in col_names:
            conn.exec_driver_sql(
                "ALTER TABLE videos ADD COLUMN summary_status VARCHAR(20) NOT NULL DEFAULT 'pending';",
            )


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a transactional SQLAlchemy session.
    """

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

