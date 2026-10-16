from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .errors import ParseError
from .parsing import clean_text, extract_json_ld_product, extract_meta_product


@dataclass
class ScrapeResult:
    name: str
    store: str
    price: float
    currency: str = "BRL"
    source: str = ""  # which layer found the price: json_ld | markup | meta


# A layer takes the parsed page and returns (name, price); either may be None.
Layer = Callable[[BeautifulSoup], tuple[str | None, float | None]]


class BaseScraper(ABC):
    """One subclass per store. Subclasses only say *where* to look;
    the layered fallback logic lives here."""

    store: str  # stable id saved in the database, e.g. "amazon"
    domains: tuple[str, ...]  # hosts (and subdomains) this scraper handles

    def matches(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in self.domains)

    def check_blocked(self, html: str, soup: BeautifulSoup) -> None:
        """Raise BlockedError when the page is a captcha/anti-bot wall."""

    @abstractmethod
    def markup_layer(self, soup: BeautifulSoup) -> tuple[str | None, float | None]:
        """Store-specific CSS selectors."""

    def layers(self) -> list[tuple[str, Layer]]:
        """Order matters: first layer that yields a price wins.
        Structured data is more stable than CSS classes, so it goes first."""
        return [
            ("json_ld", extract_json_ld_product),
            ("markup", self.markup_layer),
            ("meta", extract_meta_product),
        ]

    def parse(self, html: str) -> ScrapeResult:
        soup = BeautifulSoup(html, "html.parser")
        self.check_blocked(html, soup)

        name: str | None = None
        for source, layer in self.layers():
            layer_name, price = layer(soup)
            name = name or layer_name
            if price is not None:
                return ScrapeResult(
                    name=name or self._title_fallback(soup),
                    store=self.store,
                    price=price,
                    source=source,
                )
        raise ParseError(f"Couldn't find the price on this {self.store} page")

    @staticmethod
    def _title_fallback(soup: BeautifulSoup) -> str:
        title = clean_text(soup.title.string if soup.title else None)
        return title or "Unnamed product"
