from bs4 import BeautifulSoup

from .base import BaseScraper
from .parsing import clean_text, parse_br_price


class MercadoLivreScraper(BaseScraper):
    store = "mercado_livre"
    domains = ("mercadolivre.com.br", "mercadolivre.com", "mercadolibre.com")

    def markup_layer(self, soup: BeautifulSoup):
        title = soup.select_one("h1.ui-pdp-title")
        name = clean_text(title.get_text()) if title else None

        # The main price block; discounted-from prices live in <s> tags, skip those.
        block = soup.select_one(".ui-pdp-price__second-line .andes-money-amount") or soup.select_one(
            ".ui-pdp-price .andes-money-amount:not(.andes-money-amount--previous)"
        )
        price = None
        if block:
            fraction = block.select_one(".andes-money-amount__fraction")
            cents = block.select_one(".andes-money-amount__cents")
            if fraction:
                price = parse_br_price(
                    f"{fraction.get_text()},{cents.get_text() if cents else '00'}"
                )
        return name, price

    def list_price(self, soup: BeautifulSoup):
        block = soup.select_one(".ui-pdp-price__original-value .andes-money-amount")
        if not block:
            return None
        fraction = block.select_one(".andes-money-amount__fraction")
        cents = block.select_one(".andes-money-amount__cents")
        if not fraction:
            return None
        return parse_br_price(f"{fraction.get_text()},{cents.get_text() if cents else '00'}")
