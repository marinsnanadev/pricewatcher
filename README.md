# Price Watcher — Price Tracking Full Stack

A full-stack price tracker for online stores, combining a React front-end with a Python (FastAPI) back-end. You paste a product URL, set a target price, and the system checks it on a schedule, keeps the price history, and alerts you by email or signed webhook when the price drops. The dashboard updates live as the worker collects new prices.

![react](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)
![vite](https://img.shields.io/badge/Vite-6-646CFF?logo=vite&logoColor=white)
![python](https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white)
![fastapi](https://img.shields.io/badge/FastAPI-005571?logo=fastapi)
![sqlite](https://img.shields.io/badge/SQLite-07405E?logo=sqlite&logoColor=white)
![postgres](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![celery](https://img.shields.io/badge/Celery-37814A?logo=celery&logoColor=white)
![redis](https://img.shields.io/badge/Redis-DC382D?logo=redis&logoColor=white)

---

## About the project

Price Watcher began as a front-end-only prototype with a mocked data layer and evolved into a complete full-stack application. The objective was to build something close to a production architecture, including:

- A custom REST API built in Python, with the same contract the front-end had been using against its mock
- A relational database (SQLAlchemy + Alembic migrations) persisting users, products, price history, scraping attempts and notifications
- User authentication with hashed passwords and JWT-based sessions
- Layered scrapers, one per store, that keep working when a page changes its markup
- Scheduled background jobs with retries, backoff and jitter
- Price alerts delivered through an outbox, so a notification is never lost or sent twice
- Real-time updates pushed to the browser over WebSocket

## Technology Stack

**Front-end**
- React 18 and React Router
- Vite
- Custom CSS
- Tests with the Node.js built-in test runner

**Back-end**
- Python 3
- FastAPI
- SQLAlchemy 2 (ORM) and Alembic (migrations)
- SQLite (local development) and PostgreSQL, selected through the `DATABASE_URL` variable
- Uvicorn (ASGI server)
- JWT authentication with bcrypt password hashing
- Celery (worker and beat) with Redis as broker and pub/sub bus
- httpx and BeautifulSoup for scraping
- Tests with pytest, using saved HTML fixtures and fakeredis (no internet or Redis needed)

## Features

- User registration and login (hashed password, JWT-based session)
- Add a product by URL: the API scrapes the name and current price right away
- Per-product target price, check interval and active/paused state
- Price history per product, shown as a chart
- Scrapers for Amazon and Mercado Livre behind a common interface; adding a store is one new class and one line in the registry
- Three scraping layers per store, tried in order: JSON-LD, store markup, then OpenGraph/meta tags, with the layer that worked recorded on every attempt
- Blocked pages (captcha) are detected and reported instead of being parsed as a price
- Scheduled checks with Celery beat: one job per due product, a random start delay and ±10% on the next interval so jobs never all hit the stores at once
- Network errors and blocks are retried up to 3 times with exponential backoff and jitter; parse errors are not retried, since a retry won't fix a changed layout
- Every attempt is saved in `scrape_runs` (status, price, which layer found it, duration, error)
- The price history only grows when the price moves, plus one heartbeat point per day
- "Check now" button to queue an immediate check
- Price alerts by email and by webhook signed with HMAC-SHA256 (with timestamp for replay protection)
- Alert rules with cooldown and de-duplication, so the same alert is never sent ten times
- Outbox pattern for notifications: saved in the same transaction as the new price, delivered by a worker, re-queued automatically if Redis was down
- SSRF protection on webhook URLs, checked when saving and again right before sending
- Notification history with delivery status
- Live dashboard over WebSocket: prices change in place, the chart gets the new point, and a toast pops up when an alert fires
- Automatic WebSocket reconnect; the front-end refetches from the REST API on every reconnect, so the socket is an optimization and never the source of truth
- Auto-generated interactive API documentation (Swagger)
- Automated test suite on both the back-end (pytest) and front-end

## How it works

```
                    ┌────────────────────┐
  Browser  ◀──────▶ │   FastAPI (REST)   │ ◀──▶ SQLite / PostgreSQL
 (React)   ◀─ ws ── │   + /ws endpoint   │
                    └─────────▲──────────┘
                              │ pub/sub (one channel per user)
┌────────────┐  queue   ┌─────┴──────┐
│ Celery beat│ ───────▶ │   Redis    │
└────────────┘          └─────▲──────┘
                              │ jobs
                        ┌─────┴──────┐        ┌────────────────┐
                        │   Worker   │ ─────▶ │ Stores (scrape)│
                        └────────────┘        └────────────────┘
                              │ email / signed webhook
                              ▼
                         Notifications
```

Three back-end processes run side by side: the **API**, a **worker** (does the scraping and sends the alerts) and **beat** (a clock that, every minute, queues the products whose time has come). The worker and the API are different processes, so they talk to each other through Redis.

## API Endpoints

**Authentication**

| Method | Route | Description |
|--------|------|-----------|
| POST | `/auth/register` | Creates a new account |
| POST | `/auth/login` | Form-encoded (`username` = email); returns a JWT |
| GET | `/auth/me` | Returns the authenticated user's data |

**Products** (require the `Authorization: Bearer {token}` header)

| Method | Route | Description |
|--------|------|-----------|
| GET | `/products` | Lists the user's products |
| POST | `/products` | Creates a product (scrapes the URL) |
| GET | `/products/{id}` | Returns a product |
| PATCH | `/products/{id}` | Updates a product (target price, interval, active) |
| DELETE | `/products/{id}` | Deletes a product |
| GET | `/products/{id}/history` | Returns the price history |
| POST | `/products/{id}/check` | Queues an immediate check (202) |
| GET | `/products/{id}/runs` | Returns the latest scraping attempts |

**Notifications** (require authentication)

| Method | Route | Description |
|--------|------|-----------|
| GET / PUT | `/settings/notifications` | Reads / updates `email_enabled` and `webhook_url` (null removes it) |
| POST | `/settings/notifications/rotate-secret` | Generates a new webhook signing secret |
| POST | `/settings/notifications/test` | Sends a test through every enabled channel |
| GET | `/notifications` | Delivery history (`?product_id=` to filter) |

**Meta and real time**

| Method | Route | Description |
|--------|------|-----------|
| GET | `/health` | Health check |
| WS | `/ws` | Live events (see [Live updates](#live-updates-websocket)) |

Interactive documentation is available at `/docs` while the server is running.

## Alerts

When a check finds a price at or below the product's `target_price`, the user is notified.

- `target_reached`: price ≤ target while the alert is *armed*. Alerting disarms it.
- When the price climbs back above the target, the alert is armed again.
- `further_drop`: already alerted, but the price fell another 3% below the last alerted price **and** 6 hours passed. Anything else stays quiet.
- A product created already under its target doesn't alert instantly; it waits for a climb first.

Deliveries retry up to 5 times with exponential backoff, and a notification is never sent twice. A beat task re-queues pending rows every 5 minutes.

**Email:** `EMAIL_BACKEND=console` (default) only prints the email in the worker log. Use `EMAIL_BACKEND=smtp` plus the `SMTP_*` variables to really send.

**Webhook:** a JSON `POST` with these headers:

- `X-PriceWatcher-Event`: `price.alert` or `webhook.test`
- `X-PriceWatcher-Delivery`: unique id (use it to ignore duplicates)
- `X-PriceWatcher-Signature`: `t=<unix time>,v1=<hex>`

To verify it, compute `HMAC-SHA256(secret, "<t>.<raw body>")`, compare it with `v1` in constant time, and reject old timestamps:

```python
import hashlib, hmac, time

def verify(secret: str, header: str, raw_body: bytes) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    if abs(time.time() - int(parts["t"])) > 300:
        return False
    expected = hmac.new(secret.encode(), parts["t"].encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])
```

**Security:** webhook URLs can't point to localhost, private or cloud-metadata addresses (SSRF), and redirects are not followed. For local testing only, set `ALLOW_PRIVATE_WEBHOOKS=true` (or use a public inspector such as webhook.site).

## Live updates (WebSocket)

| Direction | Message |
|---|---|
| client → server | `{"type":"auth","token":"<jwt>"}` as the **first** message (5s limit). The token goes in the message, never in the URL, so it can't leak into access logs. |
| server → client | `{"type":"ready"}` once subscribed |
| server → client | `{"type":"product.checked","data":{...}}` after every check |
| server → client | `{"type":"alert.triggered","data":{...}}` when a price alert fires |
| server → client | `{"type":"heartbeat"}` every 25s when idle |
| client → server | `ping` → `{"type":"pong"}` |
| close code `4401` | auth failed: the client must **not** retry |

Events are live-only (no replay), and publishing is best-effort: if Redis hiccups, the check still succeeds and is saved. Behind a reverse proxy (nginx, Caddy), the proxy must allow the WebSocket upgrade.

## Running the project locally

### Prerequisites
- [Node.js](https://nodejs.org/) installed
- [Python 3](https://www.python.org/downloads/) installed
- Redis (the easiest way is Docker, shown below)

### 1. Clone the repository

```bash
git clone https://github.com/marinsnanadev/pricewatcher.git
cd pricewatcher
```

### 2. Start Redis

```bash
docker run -d --name pw-redis -p 6379:6379 redis:7
```

### 3. Running the back-end

```bash
cd backend
python -m venv .venv

# Activate the virtual environment
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt

# Copy the example variables and set JWT_SECRET
# Windows: Copy-Item .env.example .env
cp .env.example .env

# Create the tables
alembic upgrade head

# Start the API
uvicorn app.main:app --reload
```

The back-end will be available at `http://localhost:8000`, with the docs at `http://localhost:8000/docs`.

In two more terminals (also inside the virtual environment, from the `backend` folder), start the worker and beat:

```bash
celery -A app.celery_app worker -l info
celery -A app.celery_app beat -l info
```

> **Windows:** Celery's default pool doesn't work there. Start the worker with `celery -A app.celery_app worker -l info --pool=solo`.

> **PowerShell:** if `Activate.ps1` is blocked ("running scripts is disabled"), run once `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. If `alembic` or `uvicorn` are not recognized, the virtual environment is not active.

The variables in `backend/.env`:

| Variable | Description | Default |
| -------- | ----------- | ------- |
| `DATABASE_URL` | SQLAlchemy connection string. Use a PostgreSQL URL in production | `sqlite:///./pricewatcher.db` |
| `JWT_SECRET` | Key used to sign login tokens. **Change it.** | insecure development key |
| `JWT_EXPIRE_MINUTES` | Token lifetime in minutes | `1440` |
| `CORS_ORIGINS` | Front-end URLs allowed to call the API, comma-separated | `http://localhost:5174,http://localhost:5173` |
| `REDIS_URL` | Redis used by Celery and by the real-time bus | `redis://localhost:6379/0` |
| `DEFAULT_CHECK_INTERVAL_MINUTES` | Default time between checks of a product | `360` |
| `EMAIL_BACKEND` | `console` (only logs) or `smtp` | `console` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | SMTP settings, used when `EMAIL_BACKEND=smtp` | unset |
| `ALLOW_PRIVATE_WEBHOOKS` | `true` only in local dev, to test webhooks against localhost receivers | `false` |

#### Trying a scraper on its own

```bash
python -m app.services.scraping "https://www.amazon.com.br/dp/XXXXXXXXXX"
```

Stores may answer with a captcha, which is reported as a blocked page.

#### Running the back-end tests

```bash
cd backend
python -m pytest
```

### 4. Running the front-end

In another terminal, from the project root:

```bash
cd frontend
npm install
npm run dev
```

The front-end will be available at `http://localhost:5174` and points by default to the API at `http://localhost:8000`.

Note: if the API is hosted at a different address, create `frontend/.env.local` and set the `VITE_API_URL` variable.

#### Running the front-end tests

```bash
cd frontend
npm test
```

The API, the worker, beat, Redis and the front-end need to be running simultaneously for the application to work fully.

## Project structure

```
pricewatcher/
├── backend/
│   ├── app/
│   │   ├── routers/        # auth, products, notifications, realtime (WebSocket)
│   │   ├── services/
│   │   │   ├── scraping/   # one scraper per store + registry
│   │   │   ├── notifiers/  # email, signed webhook, delivery
│   │   │   ├── alerts.py   # alert rules (armed, cooldown, further drop)
│   │   │   ├── checker.py  # runs one check and records it
│   │   │   └── realtime.py # Redis pub/sub event bus
│   │   ├── tasks.py        # Celery tasks
│   │   └── celery_app.py   # Celery and beat schedule
│   ├── alembic/            # database migrations
│   └── tests/              # pytest suite and HTML fixtures
└── frontend/
    └── src/
        ├── pages/          # dashboard, product, auth
        ├── components/     # price chart, ticker row, product form
        ├── realtime/       # WebSocket client and context
        └── api.js          # REST client
```

## Roadmap / Next steps

- Fake-discount detector: compare the advertised discount with the product's real price history
- AI verdict (Gemini): "buy now or wait?", based on trend, historical low and seasonality
- Store health panel, showing which scraper is failing so a changed page layout is noticed quickly
- Docker Compose for the whole stack (API, worker, beat, Redis, PostgreSQL, front-end)
- CI with GitHub Actions running tests and lint
- Deployment of the back-end and the front-end
- Browser extension to track a product with one click, and Telegram alerts

## Author

Developed by **Nana** — Software Engineering student, with prior experience as a full-stack developer.

[GitHub](https://github.com/marinsnanadev) 
[LinkedIn](https://www.linkedin.com/in/gianna-marins-734944234/)