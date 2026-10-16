# Price Watcher — backend

FastAPI + SQLAlchemy 2 + Alembic. SQLite for now, Postgres later (just change `DATABASE_URL`).

## Run

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set JWT_SECRET
alembic upgrade head        # creates the tables
uvicorn app.main:app --reload
```

Docs: http://localhost:8000/docs

## Tests

```bash
python -m pytest
```

## Endpoints

| Method | Path | |
|---|---|---|
| POST | `/auth/register` | create account |
| POST | `/auth/login` | form-encoded (`username` = email) → JWT |
| GET | `/auth/me` | current user |
| GET/POST | `/products` | list / create (scrapes the URL) |
| GET/PATCH/DELETE | `/products/{id}` | |
| GET | `/products/{id}/history` | price history |

`app/services/scraper_stub.py` is a placeholder until the real scrapers (batch 6).
