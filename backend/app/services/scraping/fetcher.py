from typing import Protocol

import httpx

from .errors import BlockedError, FetchError

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


class Fetcher(Protocol):
    """Anything that turns a URL into HTML. Tests inject a fake one; if a store
    ever needs a real browser, a Playwright-based fetcher plugs in here."""

    def get(self, url: str) -> str: ...


class HttpxFetcher:
    def __init__(self, timeout: float = 15.0, transport: httpx.BaseTransport | None = None):
        self.timeout = timeout
        self.transport = transport  # tests inject httpx.MockTransport here

    def get(self, url: str) -> str:
        try:
            with httpx.Client(
                headers=HEADERS,
                timeout=self.timeout,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(url)
        except httpx.TimeoutException as exc:
            raise FetchError("The store took too long to respond") from exc
        except httpx.HTTPError as exc:
            raise FetchError(f"Couldn't reach the store: {exc.__class__.__name__}") from exc

        if response.status_code in (403, 429, 503):
            raise BlockedError(f"The store blocked the request (HTTP {response.status_code})")
        if response.status_code >= 400:
            raise FetchError(f"The store answered HTTP {response.status_code}")
        return response.text
