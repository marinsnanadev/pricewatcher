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

## Scraping

`app/services/scraping/` — one scraper per store (`amazon.py`, `mercadolivre.py`), each trying
**JSON-LD → store markup → OpenGraph meta** and returning which layer worked (`source`).
Adding a store = one new class + one line in `registry.py`.

Try it against a real product:

```bash
python -m app.services.scraping "https://www.amazon.com.br/dp/XXXXXXXXXX"
```

Stores may answer with a captcha (`BlockedError`); retries/scheduling come in the jobs batch.
