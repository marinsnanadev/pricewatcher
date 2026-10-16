import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.routers.products import get_scrape_fn
from app.services.scraping import ScrapeResult, UnsupportedStoreError


def fake_scrape(url: str) -> ScrapeResult:
    """Offline stand-in for the real scraper used by API tests."""
    if "unsupported" in url:
        raise UnsupportedStoreError("This store isn't supported yet")
    return ScrapeResult(name="Fone Bluetooth Pro", store="mercado_livre", price=149.9, source="json_ld")


@pytest.fixture()
def client():
    # in-memory SQLite shared across threads, fresh for every test
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_scrape_fn] = lambda: fake_scrape
    yield TestClient(app)
    app.dependency_overrides.clear()


def signup_and_login(client, email="nana@example.com", password="supersecret1"):
    client.post("/auth/register", json={"email": email, "password": password})
    res = client.post("/auth/login", data={"username": email, "password": password})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture()
def auth(client):
    return signup_and_login(client)
