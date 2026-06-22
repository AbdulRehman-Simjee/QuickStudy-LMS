# QuickStudy LMS

AI-powered Learning Management System (LMS) — FastAPI + SQLAlchemy + SQLite.

## Project structure

- `main.py`: root ASGI entrypoint for Uvicorn
- `app/main.py`: FastAPI app factory + router registration
- `app/config.py`: environment-based settings
- `app/database.py`: SQLAlchemy engine/session base
- `app/routes/`: API routes
- `app/models/`: ORM models (to be added)
- `app/services/`: AI/business logic (to be added)
- `app/utils/`: shared utilities

## Setup (Windows)

Create and activate a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file (optional) by copying `.env.example`.

## Run the API

```bash
python main.py
```

By default the API listens on `http://localhost:8001`. You can override this via
`API_HOST` and `API_PORT` in your `.env` file.

## Test endpoint

- `GET /quickstudy/welcome`

