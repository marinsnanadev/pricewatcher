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

## Alerts (email + signed webhook)

When a check finds a price at or below the product's `target_price`, the user is notified.

**When an alert fires** (per product, only if a target is set):

- `target_reached`: price <= target while the alert is *armed*. Alerting disarms it.
- Price climbs back above the target -> armed again.
- `further_drop`: already alerted, but the price fell another 3% below the last alerted price
  **and** 6h passed. Anything else stays quiet, so you never get the same alert ten times.
- A product created already under its target doesn't alert instantly; it waits for a climb first.

**How it is delivered** (outbox pattern): the `notifications` row is saved in the *same transaction*
as the new price, then a worker delivers it. If Redis is down at that moment nothing is lost:
a beat task (`retry_pending_notifications`) re-queues pending rows every 5 minutes.
Deliveries retry up to 5 times with exponential backoff; a notification is never sent twice.

**Endpoints**

| Method | Path | |
|---|---|---|
| GET/PUT | `/settings/notifications` | `email_enabled`, `webhook_url` (null removes it) |
| POST | `/settings/notifications/rotate-secret` | new webhook signing secret |
| POST | `/settings/notifications/test` | sends a test through every enabled channel |
| GET | `/notifications` | delivery history (`?product_id=`) |

**Email:** `EMAIL_BACKEND=console` (default) only prints the email in the worker log.
Use `EMAIL_BACKEND=smtp` plus the `SMTP_*` variables to really send.

**Webhook:** a JSON `POST` with these headers:

- `X-PriceWatcher-Event`: `price.alert` or `webhook.test`
- `X-PriceWatcher-Delivery`: unique id (use it to ignore duplicates)
- `X-PriceWatcher-Signature`: `t=<unix time>,v1=<hex>`

Verify it by computing `HMAC-SHA256(secret, "<t>.<raw body>")`, comparing with `v1` in constant
time, and rejecting old timestamps (replay protection). Python example:

```python
import hashlib, hmac, time

def verify(secret: str, header: str, raw_body: bytes) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    if abs(time.time() - int(parts["t"])) > 300:
        return False
    expected = hmac.new(secret.encode(), parts["t"].encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])
```

**Security:** webhook URLs can't point to localhost / private / cloud-metadata addresses (SSRF).
This is checked when saving *and* again right before sending (a hostname can change where it
points), and redirects are not followed. For local testing only, set `ALLOW_PRIVATE_WEBHOOKS=true`
(or use a public inspector such as webhook.site).

## Live updates (WebSocket)

The dashboard updates by itself when the worker finishes a check: the price changes in place
(with a green/red flash), the chart gets the new point, and a toast pops up when an alert fires.

```
worker ──publish──▶ Redis pub/sub (channel per user) ──▶ API /ws ──▶ browser tabs
```

The worker and the API are different processes, so they talk through Redis. Several API
instances work too: each one subscribes to the channels of its connected users.

**Protocol** (`/ws`):

| Direction | Message |
|---|---|
| client → server | `{"type":"auth","token":"<jwt>"}` as the **first** message (5s limit). The token goes in the message, never in the URL, so it can't leak into access logs. |
| server → client | `{"type":"ready"}` once subscribed. Everything that happens after this reaches the client. |
| server → client | `{"type":"product.checked","data":{...}}` after every check (price, check times, error). |
| server → client | `{"type":"alert.triggered","data":{...}}` when a price alert fires. |
| server → client | `{"type":"heartbeat"}` every 25s when idle (keeps proxies from closing the socket). |
| client → server | `ping` → `{"type":"pong"}` |
| close code `4401` | auth failed: the client must **not** retry, the user has to sign in again. |

Good to know:

- Events are live-only (no replay). So the frontend refetches from the REST API every time it
  **re**-connects, and treats the WebSocket as an optimization, never as the source of truth.
- Publishing is best-effort: if Redis hiccups, the check still succeeds and is saved.
- Failed fetches are retried by Celery; the error event is only sent after the last retry,
  so the UI doesn't flicker.
- Behind nginx/Caddy/etc. the proxy must allow the WebSocket upgrade (`Upgrade` and `Connection` headers).
- Each open socket holds one Redis connection (pub/sub). Fine for this scale; for thousands of
  simultaneous users you'd share one subscriber per API process.

## Deal check, AI verdict and store status

**Is the discount real?** (`GET /products/{id}/insights`) Compares what the store *advertises*
(the crossed-out "de R$ X" price, scraped next to the real one) with the price history we tracked:

| Verdict | Meaning |
|---|---|
| `genuine_deal` | clearly below its usual price, at or near its lowest |
| `fair_price` | nothing special, nothing suspicious |
| `price_above_usual` | costs more than it normally does |
| `misleading_discount` | advertised discount is much bigger than the real one |
| `fake_discount` | the "original" price is fiction (nobody paid it), or the price was hiked and then "discounted" back |
| `insufficient_data` | under ~5 checks / 7 days: it says so instead of guessing |

The "usual price" is the median of the last 90 days, ignoring the last 3. Each result also says
how confident it is (low/medium/high, from how much history there is).

**Should I buy now?** Two layers: a deterministic **rule-based** verdict (always available, free),
and, if `GEMINI_API_KEY` is set, **Gemini** writes the verdict from the same numbers. Guardrails:

- Gemini only receives numbers, never the product name or page text (scraped text is untrusted).
- Its answer is validated against a schema (action, confidence 0-1, short reasoning) and a bad
  or empty answer, a timeout (10s) or an HTTP error falls back to the rules.
- The deterministic checks keep a **veto**: Gemini can't say "buy now" on a fake/misleading
  discount, a price above usual, or too little data.
- Cost control: the verdict is cached and only recomputed when the situation really changed
  (or after 12h). "Refresh" has a 5 minute cooldown, and each user gets 20 fresh AI calls per
  hour; past that, the rule-based verdict is used instead of failing.

**Store status** (`GET /stores/health`): per store, over the last 24h: success rate, p50/p95,
which extraction layer found the prices, error counts and a diagnosis: `layout_changed`
(page loaded, price not found), `blocked` (captcha) or `network`. It aggregates every user's
checks and exposes no individual data.

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
| GET | `/products/{id}/insights` | deal check + buy/wait verdict (`?refresh=true`) |
| GET | `/stores/health` | scraper health per store (last 24h) |

## Scraping

`app/services/scraping/` — one scraper per store (`amazon.py`, `mercadolivre.py`), each trying
**JSON-LD → store markup → OpenGraph meta** and returning which layer worked (`source`).
Adding a store = one new class + one line in `registry.py`.

Try it against a real product:

```bash
python -m app.services.scraping "https://www.amazon.com.br/dp/XXXXXXXXXX"
```

Stores may answer with a captcha (`BlockedError`); retries/scheduling come in the jobs batch.