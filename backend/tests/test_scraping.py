from pathlib import Path

import pytest

from app.services.scraping import (
    BlockedError,
    FetchError,
    ParseError,
    UnsupportedStoreError,
    get_scraper,
    scrape,
)
from app.services.scraping.amazon import AmazonScraper
from app.services.scraping.mercadolivre import MercadoLivreScraper
from app.services.scraping.parsing import parse_br_price, parse_machine_price

FIXTURES = Path(__file__).parent / "fixtures"


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    def __init__(self, page: str | None = None, error: Exception | None = None):
        self.page, self.error, self.calls = page, error, []

    def get(self, url: str) -> str:
        self.calls.append(url)
        if self.error:
            raise self.error
        return self.page


# ---------- price parsing ----------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("R$ 1.299,90", 1299.90),
        ("R$\xa01.299,90", 1299.90),
        ("599,00", 599.0),
        ("599", 599.0),
        ("1.299", 1299.0),
        ("1.299.000", 1299000.0),
        ("49,9", 49.9),
        ("grátis", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_br_price(text, expected):
    assert parse_br_price(text) == expected


def test_parse_machine_price():
    assert parse_machine_price("199.9") == 199.9
    assert parse_machine_price(150) == 150.0
    assert parse_machine_price("abc") is None
    assert parse_machine_price(0) is None


# ---------- routing by domain ----------

@pytest.mark.parametrize(
    "url, scraper_cls",
    [
        ("https://www.amazon.com.br/dp/B0TEST", AmazonScraper),
        ("https://amazon.com/dp/B0TEST", AmazonScraper),
        ("https://produto.mercadolivre.com.br/MLB-123-fone", MercadoLivreScraper),
        ("https://www.mercadolivre.com.br/p/MLB123", MercadoLivreScraper),
    ],
)
def test_registry_routes_by_domain(url, scraper_cls):
    assert isinstance(get_scraper(url), scraper_cls)


@pytest.mark.parametrize(
    "url",
    ["https://example.com/x", "https://notamazon.com.br/x", "https://amazon.com.evil.io/x", "not-a-url"],
)
def test_registry_rejects_unknown_or_lookalike_domains(url):
    with pytest.raises(UnsupportedStoreError):
        get_scraper(url)


def test_unsupported_store_fails_before_any_request():
    fetcher = FakeFetcher(html("generic_meta.html"))
    with pytest.raises(UnsupportedStoreError):
        scrape("https://example.com/x", fetcher=fetcher)
    assert fetcher.calls == []


# ---------- Amazon ----------

def test_amazon_picks_real_price_not_struck_list_price():
    result = scrape("https://www.amazon.com.br/dp/B0TEST", FakeFetcher(html("amazon_product.html")))
    assert result.store == "amazon"
    assert result.price == 1299.90
    assert result.list_price == 1899.0
    assert result.name == "Fone de Ouvido Bluetooth XYZ Pro com Cancelamento de Ruído"
    assert result.source == "markup"


def test_no_list_price_when_the_page_shows_none():
    result = scrape("https://www.amazon.com.br/dp/B0TEST", FakeFetcher(html("amazon_whole_fraction.html")))
    assert result.list_price is None
    result = scrape("https://produto.mercadolivre.com.br/MLB-1", FakeFetcher(html("ml_jsonld.html")))
    assert result.list_price is None


def test_list_price_below_the_real_price_is_discarded():
    page = html("amazon_product.html").replace("R$ 1.899,00", "R$ 899,00")  # nonsense "was" price
    result = scrape("https://www.amazon.com.br/dp/B0TEST", FakeFetcher(page))
    assert result.price == 1299.90 and result.list_price is None


def test_amazon_whole_plus_fraction_layout():
    result = scrape("https://www.amazon.com.br/dp/B0TEST", FakeFetcher(html("amazon_whole_fraction.html")))
    assert result.price == 49.90
    assert result.name == "Cabo USB-C 2m"


def test_amazon_captcha_is_reported_as_blocked():
    with pytest.raises(BlockedError):
        scrape("https://www.amazon.com.br/dp/B0TEST", FakeFetcher(html("amazon_captcha.html")))


# ---------- Mercado Livre ----------

def test_mercadolivre_prefers_json_ld():
    result = scrape("https://produto.mercadolivre.com.br/MLB-1", FakeFetcher(html("ml_jsonld.html")))
    assert (result.name, result.price, result.source) == ("Fone Bluetooth Pro Preto", 199.9, "json_ld")
    assert result.store == "mercado_livre"


def test_mercadolivre_falls_back_to_markup():
    result = scrape("https://produto.mercadolivre.com.br/MLB-2", FakeFetcher(html("ml_markup.html")))
    assert result.price == 1249.90  # not the struck-through 1.899
    assert result.list_price == 1899.0
    assert result.name == "Teclado Mecânico RGB"
    assert result.source == "markup"


def test_falls_back_to_meta_tags_last():
    result = scrape("https://produto.mercadolivre.com.br/MLB-3", FakeFetcher(html("generic_meta.html")))
    assert (result.name, result.price, result.source) == ("Mouse Gamer Sem Fio", 159.5, "meta")


def test_page_without_price_raises_parse_error():
    with pytest.raises(ParseError):
        scrape("https://produto.mercadolivre.com.br/MLB-4", FakeFetcher(html("no_price.html")))


def test_fetch_errors_propagate():
    with pytest.raises(FetchError):
        scrape("https://www.amazon.com.br/dp/B0TEST", FakeFetcher(error=FetchError("timeout")))


# ---------- HttpxFetcher (status handling, no real network) ----------

import httpx  # noqa: E402

from app.services.scraping import HttpxFetcher  # noqa: E402


def fetcher_returning(status: int, body: str = "<html></html>"):
    transport = httpx.MockTransport(lambda request: httpx.Response(status, text=body))
    return HttpxFetcher(transport=transport)


def test_httpx_fetcher_returns_body_on_200():
    assert fetcher_returning(200, "<p>ok</p>").get("https://x.test") == "<p>ok</p>"


@pytest.mark.parametrize("status", [403, 429, 503])
def test_httpx_fetcher_flags_blocks(status):
    with pytest.raises(BlockedError):
        fetcher_returning(status).get("https://x.test")


def test_httpx_fetcher_other_errors():
    with pytest.raises(FetchError) as exc:
        fetcher_returning(404).get("https://x.test")
    assert not isinstance(exc.value, BlockedError)


def test_httpx_fetcher_timeout():
    def boom(request):
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(FetchError):
        HttpxFetcher(transport=httpx.MockTransport(boom)).get("https://x.test")
