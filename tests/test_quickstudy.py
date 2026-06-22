from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register ORM models on Base.metadata
from app.database import Base, get_db
from app.main import app
from app.models.audio import Audio, AudioStatus
from app.models.quiz import Mcq
from app.models.summary import Summary, SummaryStatus
from app.models.transcript import Transcript, TranscriptStatus
from app.models.user import User, UserPlan, UserRole
from app.models.video import Video, VideoStatus
from app.services.auth_service import create_user
from app.services.plan_service import FREE_MAX_VIDEOS_PER_MONTH
from app.utils.security import create_access_token

TEST_PASSWORD = "password123"


@pytest.fixture()
def test_engine():
    """In-memory SQLite engine; isolated from production ``quickstudy.db``."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db_session(test_engine) -> Session:
    session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)()
    yield session
    session.close()


@pytest.fixture()
def client(test_engine, tmp_path, monkeypatch):
    """FastAPI client with overridden DB and temp uploads directory."""

    session_factory = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    uploads = tmp_path / "uploads"
    (uploads / "videos").mkdir(parents=True, exist_ok=True)

    from app.config import get_settings

    settings = get_settings()
    original_uploads = settings.uploads_dir
    settings.uploads_dir = uploads

    # Prevent TestClient lifespan from touching the production SQLite file.
    monkeypatch.setattr("app.database.init_db", lambda: None)

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        settings.uploads_dir = original_uploads


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}@example.com"


def _signup(client: TestClient, *, email: str, role: str = "student") -> None:
    response = client.post(
        "/auth/signup",
        json={
            "full_name": "Test User",
            "email": email,
            "password": TEST_PASSWORD,
            "role": role,
        },
    )
    assert response.status_code == 201, response.text


def _login_headers(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_user_in_db(db: Session, *, email: str, role: str = "student", plan: str = "free") -> User:
    user = create_user(
        db,
        full_name="DB User",
        email=email,
        password=TEST_PASSWORD,
        role=UserRole(role),
    )
    user.plan = plan
    db.commit()
    db.refresh(user)
    return user


def _auth_headers_for_user(user: User) -> dict[str, str]:
    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def _create_video(
    db: Session,
    *,
    user_id: int,
    title: str = "Lecture",
    file_path: str | None = None,
) -> Video:
    path = file_path or f"uploads/videos/{uuid.uuid4().hex}.mp4"
    video = Video(
        title=title,
        filename=Path(path).name,
        file_path=path,
        uploaded_by=user_id,
        file_size=1024,
        duration=60.0,
        status=VideoStatus.uploaded.value,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


def _create_mcq_set(db: Session, *, video_id: int, count: int = 3) -> list[Mcq]:
    rows: list[Mcq] = []
    for i in range(count):
        letter = "A"
        row = Mcq(
            video_id=video_id,
            question=f"Question {i + 1}?",
            option_a="Correct",
            option_b="Wrong B",
            option_c="Wrong C",
            option_d="Wrong D",
            correct_answer=letter,
            explanation="Because A.",
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def _create_transcript(db: Session, *, video_id: int) -> Transcript:
    audio = Audio(
        video_id=video_id,
        filename="test.mp3",
        file_path="uploads/audio/test.mp3",
        file_size=100,
        status=AudioStatus.done.value,
    )
    db.add(audio)
    db.flush()
    transcript = Transcript(
        video_id=video_id,
        audio_id=audio.id,
        transcript_text="Transcript for tests.",
        status=TranscriptStatus.done.value,
    )
    db.add(transcript)
    db.commit()
    db.refresh(transcript)
    return transcript


def _create_summary(db: Session, *, video_id: int) -> Summary:
    transcript = _create_transcript(db, video_id=video_id)
    summary = Summary(
        video_id=video_id,
        transcript_id=transcript.id,
        summary_text="Summary text for tests.",
        summary_type="short",
        status=SummaryStatus.done.value,
    )
    db.add(summary)
    db.commit()
    db.refresh(summary)
    return summary


# --- AUTH TESTS ---


def test_signup_valid(client: TestClient):
    email = _unique_email("signup")
    response = client.post(
        "/auth/signup",
        json={
            "full_name": "New Student",
            "email": email,
            "password": TEST_PASSWORD,
            "role": "student",
        },
    )
    assert response.status_code == 201
    assert response.json()["message"] == "Signup successful"


def test_signup_duplicate_email(client: TestClient):
    email = _unique_email("dup")
    _signup(client, email=email)
    response = client.post(
        "/auth/signup",
        json={
            "full_name": "Another",
            "email": email,
            "password": TEST_PASSWORD,
            "role": "student",
        },
    )
    assert response.status_code == 409


def test_login_valid(client: TestClient):
    email = _unique_email("login")
    _signup(client, email=email)
    response = client.post("/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == email


def test_login_wrong_password(client: TestClient):
    email = _unique_email("badpass")
    _signup(client, email=email)
    response = client.post("/auth/login", json={"email": email, "password": "wrong-password"})
    assert response.status_code == 401


def test_protected_route_no_token(client: TestClient):
    response = client.get("/auth/me")
    assert response.status_code == 401


# --- VIDEO TESTS ---


def test_video_upload_valid(client: TestClient, tmp_path):
    email = _unique_email("upload")
    _signup(client, email=email)
    headers = _login_headers(client, email)

    video_bytes = b"\x00" * 128
    response = client.post(
        "/videos/upload",
        headers=headers,
        data={"title": "My Lecture"},
        files={"file": ("lecture.mp4", video_bytes, "video/mp4")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["video"]["title"] == "My Lecture"
    assert body["video"]["uploaded_by"] is not None


def test_video_upload_free_plan_limit(client: TestClient, db_session: Session):
    email = _unique_email("limit")
    user = _create_user_in_db(db_session, email=email, plan=UserPlan.free.value)
    headers = _auth_headers_for_user(user)

    for i in range(FREE_MAX_VIDEOS_PER_MONTH):
        _create_video(db_session, user_id=user.id, title=f"Video {i}")

    response = client.post(
        "/videos/upload",
        headers=headers,
        data={"title": "Over limit"},
        files={"file": ("over.mp4", b"bytes", "video/mp4")},
    )
    assert response.status_code == 403
    assert "10 videos" in response.json()["detail"]


def test_video_rename(client: TestClient, db_session: Session):
    email = _unique_email("rename")
    user = _create_user_in_db(db_session, email=email)
    video = _create_video(db_session, user_id=user.id, title="Old Title")
    headers = _auth_headers_for_user(user)

    response = client.patch(
        f"/videos/{video.id}/rename",
        headers=headers,
        json={"title": "New Title"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "New Title"


def test_video_delete(client: TestClient, db_session: Session, tmp_path):
    email = _unique_email("delete")
    user = _create_user_in_db(db_session, email=email)
    video_path = tmp_path / "uploads" / "videos" / "delete_me.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"video")
    video = _create_video(db_session, user_id=user.id, file_path=str(video_path))
    video_id = video.id
    headers = _auth_headers_for_user(user)

    response = client.delete(f"/videos/{video_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["video_id"] == video_id
    db_session.expire_all()
    assert db_session.scalar(select(Video).where(Video.id == video_id)) is None


# --- QUIZ TESTS ---


def test_mcq_submission_full(client: TestClient, db_session: Session):
    email = _unique_email("mcqfull")
    user = _create_user_in_db(db_session, email=email)
    video = _create_video(db_session, user_id=user.id)
    mcqs = _create_mcq_set(db_session, video_id=video.id, count=3)
    headers = _auth_headers_for_user(user)

    answers = [{"question_id": m.id, "selected_option": m.correct_answer} for m in mcqs]
    response = client.post(
        f"/assessment/submit/mcq/{video.id}",
        headers=headers,
        json={"answers": answers},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_correct"] == 3
    assert body["total_questions"] == 3
    assert body["total_score_text"] == "3/3"


def test_mcq_submission_partial(client: TestClient, db_session: Session):
    email = _unique_email("mcqpart")
    user = _create_user_in_db(db_session, email=email)
    video = _create_video(db_session, user_id=user.id)
    mcqs = _create_mcq_set(db_session, video_id=video.id, count=3)
    headers = _auth_headers_for_user(user)

    response = client.post(
        f"/assessment/submit/mcq/{video.id}",
        headers=headers,
        json={"answers": [{"question_id": mcqs[0].id, "selected_option": "A"}]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_correct"] == 1
    assert body["total_questions"] == 3
    assert body["total_score_text"] == "1/3"


def test_quiz_regenerate_free_plan_blocked(client: TestClient, db_session: Session):
    email = _unique_email("regen")
    user = _create_user_in_db(db_session, email=email, plan=UserPlan.free.value)
    video = _create_video(db_session, user_id=user.id)
    _create_mcq_set(db_session, video_id=video.id, count=2)
    headers = _auth_headers_for_user(user)

    response = client.post(f"/quiz/generate/mcq/{video.id}", headers=headers)
    assert response.status_code == 403
    assert "Regenerating quiz" in response.json()["detail"]


# --- BILLING TESTS ---


def test_plan_upgrade(client: TestClient):
    email = _unique_email("upgrade")
    _signup(client, email=email)
    headers = _login_headers(client, email)

    response = client.post(
        "/billing/upgrade",
        headers=headers,
        json={
            "plan": "pro",
            "card_number": "4111111111111111",
            "expiry": "12/30",
            "cvv": "123",
            "name_on_card": "Test User",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["plan"] == "pro"

    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["plan"] == "pro"
    assert me.json()["pro_expires_at"] is None


def test_plan_cancel(client: TestClient):
    email = _unique_email("cancel")
    _signup(client, email=email)
    headers = _login_headers(client, email)

    client.post(
        "/billing/upgrade",
        headers=headers,
        json={
            "plan": "pro",
            "card_number": "4111111111111111",
            "expiry": "12/30",
            "cvv": "123",
            "name_on_card": "Test User",
        },
    )

    response = client.post("/billing/cancel", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "Pro access continues until" in body["message"]
    assert body["pro_expires_at"] is not None

    plan = client.get("/billing/plan", headers=headers)
    assert plan.status_code == 200
    assert plan.json()["plan"] == "pro"
    assert plan.json()["cancellation_pending"] is True


def test_pro_expiry_check(client: TestClient, db_session: Session):
    email = _unique_email("expiry")
    _signup(client, email=email)
    headers = _login_headers(client, email)
    client.post(
        "/billing/upgrade",
        headers=headers,
        json={
            "plan": "pro",
            "card_number": "4111111111111111",
            "expiry": "12/30",
            "cvv": "123",
            "name_on_card": "Test User",
        },
    )

    user = db_session.scalar(select(User).where(User.email == email))
    assert user is not None
    user.pro_expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db_session.commit()

    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["plan"] == "free"
    assert response.json()["pro_expires_at"] is None

    db_session.expire_all()
    refreshed = db_session.scalar(select(User).where(User.id == user.id))
    assert refreshed is not None
    assert refreshed.plan == UserPlan.free.value


# --- DASHBOARD TESTS ---


def test_dashboard_returns_correct_data(client: TestClient, db_session: Session):
    email = _unique_email("dash")
    user = _create_user_in_db(db_session, email=email)
    video = _create_video(db_session, user_id=user.id)
    _create_summary(db_session, video_id=video.id)
    headers = _auth_headers_for_user(user)

    response = client.get("/dashboard", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_videos_uploaded"] == 1
    assert body["summaries_generated"] == 1


def test_teacher_dashboard_access(client: TestClient):
    email = _unique_email("teacher")
    _signup(client, email=email, role="teacher")
    headers = _login_headers(client, email)

    response = client.get("/teacher/dashboard", headers=headers)
    assert response.status_code == 200
    assert "total_students" in response.json()


def test_student_cannot_access_teacher(client: TestClient):
    email = _unique_email("student")
    _signup(client, email=email, role="student")
    headers = _login_headers(client, email)

    response = client.get("/teacher/dashboard", headers=headers)
    assert response.status_code == 403
