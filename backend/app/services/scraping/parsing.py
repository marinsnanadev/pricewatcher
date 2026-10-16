"""Small helpers shared by all store scrapers (pure functions, easy to test)."""
import json
import re

from bs4 import BeautifulSoup

_NUMBER = re.compile(r"\d[\d.,]*")


def parse_br_price(text: str | None) -> float | None:
    """'R$ 1.299,90' -> 1299.9 | '599' -> 599.0 | '1.299' -> 1299.0

    Human-formatted text from Brazilian stores: '.' groups thousands and
    ',' separates decimals.
    """
    if not text:
        return None
    match = _NUMBER.search(text)
    if not match:
        return None
    raw = match.group().rstrip(".,")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", raw):
        raw = raw.replace(".", "")  # '1.299' / '1.299.000' are thousands groups
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def parse_machine_price(value) -> float | None:
    """Prices from JSON-LD / meta tags already use '.' as the decimal separator."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    return number if number > 0 else None


def clean_text(text: str | None) -> str | None:
    if not text:
        return None
    text = " ".join(text.split())
    return text or None


def _iter_nodes(data):
    """Walks any JSON-LD structure (lists, @graph, nested dicts)."""
    if isinstance(data, list):
        for item in data:
            yield from _iter_nodes(item)
    elif isinstance(data, dict):
        yield data
        for value in data.values():
            if isinstance(value, (list, dict)):
                yield from _iter_nodes(value)


def _is_type(node: dict, wanted: str) -> bool:
    kind = node.get("@type")
    return kind == wanted or (isinstance(kind, list) and wanted in kind)


def _offer_price(offers) -> float | None:
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return None
    prices = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        spec = offer.get("priceSpecification")
        candidates = [offer.get("price"), offer.get("lowPrice")]
        if isinstance(spec, dict):
            candidates.append(spec.get("price"))
        for candidate in candidates:
            price = parse_machine_price(candidate)
            if price is not None:
                prices.append(price)
                break
    return min(prices) if prices else None


def extract_json_ld_product(soup: BeautifulSoup) -> tuple[str | None, float | None]:
    """(name, price) of the first schema.org Product found in JSON-LD blocks."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _iter_nodes(data):
            if _is_type(node, "Product"):
                price = _offer_price(node.get("offers"))
                if price is not None:
                    return clean_text(node.get("name")), price
    return None, None


def meta_content(soup: BeautifulSoup, *names: str) -> str | None:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find(
            "meta", attrs={"name": name}
        ) or soup.find("meta", attrs={"itemprop": name})
        if tag and tag.get("content"):
            return tag["content"]
    return None


def extract_meta_product(soup: BeautifulSoup) -> tuple[str | None, float | None]:
    """OpenGraph / microdata fallback: og:title + product:price:amount."""
    name = clean_text(meta_content(soup, "og:title", "twitter:title"))
    price = parse_machine_price(
        meta_content(soup, "product:price:amount", "og:price:amount", "price")
    )
    return name, price
