class ScrapeError(Exception):
    """Base class for everything that can go wrong while scraping."""


class UnsupportedStoreError(ScrapeError):
    """We don't have a scraper for this domain."""


class FetchError(ScrapeError):
    """Network problem, timeout or unexpected HTTP status."""


class BlockedError(FetchError):
    """The store answered, but with a captcha / anti-bot page."""


class ParseError(ScrapeError):
    """Page loaded, but we couldn't find the name/price in it."""
