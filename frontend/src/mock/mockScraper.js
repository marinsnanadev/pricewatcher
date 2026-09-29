const STORE_NAMES = {
  "mercadolivre.com": "mercado_livre",
  "mercadolibre.com": "mercado_livre",
  "amazon.com": "amazon",
  "amazon.com.br": "amazon",
};

function detectStore(url) {
  const match = Object.keys(STORE_NAMES).find((domain) => url.includes(domain));
  return match ? STORE_NAMES[match] : "loja_desconhecida";
}

function guessProductName(url) {
  try {
    const path = new URL(url).pathname;
    const slug = path.split("/").filter(Boolean).pop() || "produto";
    const words = slug.replace(/[-_]/g, " ").replace(/\d+/g, "").trim();
    return words
      ? words.replace(/\b\w/g, (c) => c.toUpperCase())
      : "Produto sem nome identificável";
  } catch {
    return "Produto sem nome identificável";
  }
}

function randomPrice() {
  return Math.round((30 + Math.random() * 470) * 100) / 100;
}

/** Gera uma pequena variação (queda ou alta) em cima de um preço existente. */
export function fluctuate(price, maxPercent = 0.08) {
  const change = price * (Math.random() * maxPercent * 2 - maxPercent);
  return Math.max(1, Math.round((price + change) * 100) / 100);
}

export function fakeScrape(url) {
  const store = detectStore(url);
  return {
    name: guessProductName(url),
    price: randomPrice(),
    store,
  };
}
