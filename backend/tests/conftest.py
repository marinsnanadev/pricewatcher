import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db, get_session_factory
from app.main import app
from app.routers.notifications import get_enqueue_delivery
from app.routers.products import get_enqueue, get_scrape_fn
from app.services import realtime
from app.services.realtime import get_event_bus as real_get_event_bus  # the key the router depends on
from tests.fakes import InMemoryEventBus
from app.services.scraping import ScrapeResult, UnsupportedStoreError


def fake_scrape(url: str) -> ScrapeResult:
    """Offline stand-in for the real scraper used by API tests."""
    if "unsupported" in url:
        raise UnsupportedStoreError("This store isn't supported yet")
    return ScrapeResult(name="Fone Bluetooth Pro", store="mercado_livre", price=149.9, source="json_ld")


@pytest.fixture()
def session_factory():
    # in-memory SQLite shared across threads, fresh for every test
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture()
def enqueued():
    """Records the product ids the API asked the queue to check."""
    return []


@pytest.fixture(autouse=True)
def bus(monkeypatch):
    """No test ever talks to a real Redis: workers publish to this in-memory bus."""
    fake = InMemoryEventBus()
    monkeypatch.setattr(realtime, "get_event_bus", lambda: fake)
    return fake


@pytest.fixture()
def deliveries():
    """Records the notification ids the API asked the queue to deliver."""
    return []


@pytest.fixture()
def client(session_factory, enqueued, deliveries, bus):
    TestingSession = session_factory

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_scrape_fn] = lambda: fake_scrape
    app.dependency_overrides[get_enqueue] = lambda: enqueued.append
    app.dependency_overrides[get_enqueue_delivery] = lambda: deliveries.append
    app.dependency_overrides[real_get_event_bus] = lambda: bus
    app.dependency_overrides[get_session_factory] = lambda: TestingSession
    yield TestClient(app)
    app.dependency_overrides.clear()


def signup_and_login(client, email="nana@example.com", password="supersecret1"):
    client.post("/auth/register", json={"email": email, "password": password})
    res = client.post("/auth/login", data={"username": email, "password": password})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture()
def auth(client):
    return signup_and_login(client)


def make_product(db, **overrides):
    """Inserts a user + product straight into the DB (no scraping involved)."""
    from app.models import PriceHistory, Product, User

    user = db.query(User).first() or User(email="w@example.com", password_hash="x")
    db.add(user)
    db.flush()
    fields = dict(
        user_id=user.id,
        url="https://www.amazon.com.br/dp/B0TEST",
        name="Test product",
        store="amazon",
        current_price=100.0,
        active=True,
    )
    fields.update(overrides)
    product = Product(**fields)
    product.history.append(PriceHistory(price=fields["current_price"], collected_at=overrides.get("created_at")))
    db.add(product)
    db.commit()
    return product
