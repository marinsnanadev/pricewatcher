from bs4 import BeautifulSoup

from .base import BaseScraper, Layer
from .errors import BlockedError
from .parsing import clean_text, parse_br_price, extract_json_ld_product, extract_meta_product

CAPTCHA_MARKERS = ("/errors/validateCaptcha", "Type the characters you see", "Digite os caracteres")


class AmazonScraper(BaseScraper):
    store = "amazon"
    domains = ("amazon.com.br", "amazon.com")

    def check_blocked(self, html: str, soup: BeautifulSoup) -> None:
        if any(marker in html for marker in CAPTCHA_MARKERS):
            raise BlockedError("Amazon showed a captcha, try again later")

    def layers(self) -> list[tuple[str, Layer]]:
        # Amazon rarely ships JSON-LD, so its own markup goes first.
        return [
            ("markup", self.markup_layer),
            ("json_ld", extract_json_ld_product),
            ("meta", extract_meta_product),
        ]

    def markup_layer(self, soup: BeautifulSoup):
        title = soup.select_one("#productTitle")
        name = clean_text(title.get_text()) if title else None

        # ".a-text-price" is the struck-through "list price"; we want the real one.
        tag = soup.select_one(
            "#corePrice_feature_div .a-price:not(.a-text-price) .a-offscreen, "
            "#corePriceDisplay_desktop_feature_div .a-price:not(.a-text-price) .a-offscreen, "
            ".a-price:not(.a-text-price) .a-offscreen"
        )
        price = parse_br_price(tag.get_text()) if tag else None

        if price is None:  # older layout: whole + fraction in separate spans
            whole = soup.select_one(".a-price-whole")
            fraction = soup.select_one(".a-price-fraction")
            if whole:
                digits = "".join(c for c in whole.get_text() if c.isdigit())
                cents = "".join(c for c in (fraction.get_text() if fraction else "") if c.isdigit())
                price = parse_br_price(f"{digits},{cents or '00'}")
        return name, price
