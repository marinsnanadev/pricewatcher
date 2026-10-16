from .base import ScrapeResult
from .errors import (
    BlockedError,
    FetchError,
    ParseError,
    ScrapeError,
    UnsupportedStoreError,
)
from .fetcher import Fetcher, HttpxFetcher
from .registry import get_scraper


def scrape(url: str, fetcher: Fetcher | None = None) -> ScrapeResult:
    """URL in, ScrapeResult out. Raises a ScrapeError subclass on failure."""
    scraper = get_scraper(url)  # fails fast, before any network call
    html = (fetcher or HttpxFetcher()).get(url)
    return scraper.parse(html)


__all__ = [
    "scrape",
    "ScrapeResult",
    "ScrapeError",
    "UnsupportedStoreError",
    "FetchError",
    "BlockedError",
    "ParseError",
    "Fetcher",
    "HttpxFetcher",
    "get_scraper",
]
