from .amazon import AmazonScraper
from .base import BaseScraper
from .errors import UnsupportedStoreError
from .mercadolivre import MercadoLivreScraper

SCRAPERS: list[BaseScraper] = [AmazonScraper(), MercadoLivreScraper()]


def get_scraper(url: str) -> BaseScraper:
    for scraper in SCRAPERS:
        if scraper.matches(url):
            return scraper
    supported = ", ".join(s.store for s in SCRAPERS)
    raise UnsupportedStoreError(f"This store isn't supported yet (supported: {supported})")
