from fastapi import APIRouter, Depends
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(tags=["QuickStudy"])


@router.get("/welcome")
def welcome() -> dict[str, str]:
    """
    Basic health-style endpoint to verify the API is running.
    """

    return {"message": "Welcome to QuickStudy LMS API!"}


@router.get("/db-status")
def db_status(db: Session = Depends(get_db)) -> dict[str, object]:
    """
    Lightweight database connectivity check.

    Returns:
    - connection_ok: DB responds to `SELECT 1`
    - tables: currently visible tables in the schema
    - users_table_present: whether the `users` table exists
    """

    db.execute(text("SELECT 1"))
    inspector = inspect(db.bind)
    tables = inspector.get_table_names()
    return {
        "connection_ok": True,
        "tables": tables,
        "users_table_present": "users" in tables,
    }

