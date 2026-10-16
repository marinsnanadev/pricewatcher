# Price Watcher — backend

FastAPI + SQLAlchemy 2 + Alembic. SQLite for now, Postgres later (just change `DATABASE_URL`).

## Run

Run everything from the `backend` folder, **inside a virtual environment** (the `(.venv)` prefix
should show in your prompt). Without it, `pip` installs into your global Python and commands like
`alembic` may not be found.

### Linux / macOS (bash/zsh)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set JWT_SECRET
alembic upgrade head        # creates the tables
uvicorn app.main:app --reload
```

### Windows (PowerShell)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # then set JWT_SECRET
alembic upgrade head          # creates the tables
uvicorn app.main:app --reload
```

> PowerShell 5.1 does not support `&&`; run the commands one per line as above.
> If `Activate.ps1` is blocked ("running scripts is disabled"), run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### Windows (cmd.exe)

```bat
cd backend
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

### Without activating the venv (any OS)

Call the venv's Python directly. Use `.venv/bin/python` on Linux/macOS and
`.\.venv\Scripts\python` on Windows:

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

Docs: http://localhost:8000/docs

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `'&&' is not a valid statement separator` (PowerShell) | Run the commands on separate lines. |
| `source` is not recognized (Windows) | `source` is bash-only. Use `.\.venv\Scripts\Activate.ps1` (PowerShell) or `.venv\Scripts\activate.bat` (cmd). |
| `alembic` / `uvicorn` is not recognized | The venv is not active, so the scripts were installed outside your PATH. Activate the venv and reinstall, or use `python -m alembic ...` / `python -m uvicorn ...` from the venv. |
| `Activate.ps1` cannot be loaded | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again. |

## Scheduled jobs (Celery + Redis)

Three processes run side by side: the API, a **worker** (does the scraping) and **beat**
(a clock that, every minute, queues the products whose time has come).

```bash
# 1) Redis (easiest with Docker)
docker run -d --name pw-redis -p 6379:6379 redis:7

# 2) apply the new migration
alembic upgrade head

# 3) in separate terminals, all inside the venv:
uvicorn app.main:app --reload
celery -A app.celery_app worker -l info
celery -A app.celery_app beat -l info
```

> **Windows:** Celery's default pool doesn't work there. Start the worker with
> `celery -A app.celery_app worker -l info --pool=solo`.

How it works:

- Each product has its own `check_interval_minutes` (default 6h) and `next_check_at`.
  Beat runs `dispatch_due`, which enqueues one `check_product` job per due product,
  with a random start delay and ±10% on the next interval so jobs never all hit the stores at once.
- Network errors and blocks (`FetchError`) are retried up to 3 times with exponential backoff + jitter.
  Parse errors aren't retried (a retry won't fix a changed layout) — they are recorded.
- Every attempt is saved in `scrape_runs` (status, price, which layer found it, duration, error).
  The price history only grows when the price moves, plus one heartbeat point per day.
- `POST /products/{id}/check` queues a check right now; `GET /products/{id}/runs` shows the latest attempts.

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
| POST | `/products/{id}/check` | queue an immediate check (202) |
| GET | `/products/{id}/runs` | latest scraping attempts |

## Scraping

`app/services/scraping/` — one scraper per store (`amazon.py`, `mercadolivre.py`), each trying
**JSON-LD → store markup → OpenGraph meta** and returning which layer worked (`source`).
Adding a store = one new class + one line in `registry.py`.

Try it against a real product:

```bash
python -m app.services.scraping "https://www.amazon.com.br/dp/XXXXXXXXXX"
```

Stores may answer with a captcha (`BlockedError`); retries/scheduling come in the jobs batch.