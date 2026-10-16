"""Try the scrapers against a real URL:

    python -m app.services.scraping "https://www.amazon.com.br/dp/XXXXXXXXXX"
"""
import sys

from . import ScrapeError, scrape

if len(sys.argv) != 2:
    sys.exit("usage: python -m app.services.scraping <product-url>")

try:
    result = scrape(sys.argv[1])
except ScrapeError as exc:
    sys.exit(f"{exc.__class__.__name__}: {exc}")

print(f"store : {result.store}")
print(f"name  : {result.name}")
print(f"price : {result.currency} {result.price:.2f}")
print(f"found via: {result.source}")
