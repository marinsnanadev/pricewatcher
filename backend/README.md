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