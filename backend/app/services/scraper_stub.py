"""Temporary stand-in for the real scraper (batch 6).

Same idea as the frontend's mockScraper: derives a name from the URL and
returns a random price. It will be replaced by the real per-store scrapers,
keeping the same `scrape(url) -> ScrapeResult` signature.
"""
import random
from dataclasses import dataclass
from urllib.parse import urlparse

STORES = {
    "mercadolivre.com": "mercado_livre",
    "mercadolibre.com": "mercado_livre",
    "amazon.com.br": "amazon",
    "amazon.com": "amazon",
}


@dataclass
class ScrapeResult:
    name: str
    store: str
    price: float


def detect_store(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for domain, store in STORES.items():
        if domain in host:
            return store
    return "unknown_store"


def guess_name(url: str) -> str:
    slug = [p for p in urlparse(url).path.split("/") if p]
    raw = slug[-1] if slug else "product"
    words = "".join(c if not c.isdigit() else " " for c in raw.replace("-", " ").replace("_", " "))
    words = " ".join(words.split())
    return words.title() if words else "Unnamed product"


def scrape(url: str) -> ScrapeResult:
    return ScrapeResult(
        name=guess_name(url),
        store=detect_store(url),
        price=round(random.uniform(30, 500), 2),
    )
