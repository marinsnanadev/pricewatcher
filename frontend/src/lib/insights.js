// Labels and small helpers for the deal check and store health screens (pure, tested).

export const DEAL = {
  genuine_deal: { label: "Real deal", tone: "good" },
  fair_price: { label: "Fair price", tone: "neutral" },
  price_above_usual: { label: "Pricier than usual", tone: "warn" },
  misleading_discount: { label: "Misleading discount", tone: "warn" },
  fake_discount: { label: "Fake discount", tone: "bad" },
  insufficient_data: { label: "Not enough data yet", tone: "muted" },
};

export const FLAG_TEXT = {
  inflated_list_price: "In the history we tracked, it never sold near the advertised original price.",
  pre_sale_hike: "The price was raised recently, then “discounted” back to its usual level.",
  new_low: "Lowest price we've seen for this product.",
  above_usual: "Higher than its usual price.",
};

export const ACTION = {
  buy_now: { label: "Buy now", tone: "good" },
  wait: { label: "Wait", tone: "warn" },
  neutral: { label: "No clear signal", tone: "neutral" },
};

export const SOURCE_LABEL = { gemini: "AI (Gemini)", rules: "Rule-based" };

export function dealInfo(verdict) {
  return DEAL[verdict] ?? { label: verdict, tone: "muted" };
}

export function actionInfo(action) {
  return ACTION[action] ?? { label: action, tone: "neutral" };
}

/** "-40%" for a discount, "+12%" when it costs more than usual, "—" when unknown. */
export function discountText(pct) {
  if (pct == null) return "—";
  const rounded = Math.round(Math.abs(pct));
  if (rounded === 0) return "0%";
  return `${pct > 0 ? "−" : "+"}${rounded}%`; // positive pct = cheaper
}

export const HEALTH = {
  healthy: { label: "Healthy", tone: "good" },
  degraded: { label: "Degraded", tone: "warn" },
  down: { label: "Down", tone: "bad" },
  idle: { label: "No recent checks", tone: "muted" },
};

export function healthInfo(status) {
  return HEALTH[status] ?? { label: status, tone: "muted" };
}

export const DIAGNOSIS_TEXT = {
  layout_changed: "The page loads but the price isn't found. The store's layout probably changed and the scraper needs an update.",
  blocked: "The store is showing captchas or blocking requests.",
  network: "Network errors or timeouts reaching the store.",
  unsupported: "Some products point to a store we don't support.",
  unknown: "Failing for an unknown reason.",
};

export function diagnosisText(diagnosis) {
  return diagnosis ? DIAGNOSIS_TEXT[diagnosis] ?? DIAGNOSIS_TEXT.unknown : null;
}

/** 0.943 -> "94%" */
export function percentText(rate) {
  return rate == null ? "—" : `${Math.round(rate * 100)}%`;
}

export function msText(ms) {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

/** [["json_ld", 3], ["markup", 1]] with each share in % (for the little bar). */
export function layerShares(layers) {
  const entries = Object.entries(layers ?? {});
  const total = entries.reduce((sum, [, n]) => sum + n, 0);
  if (total === 0) return [];
  return entries
    .sort((a, b) => b[1] - a[1])
    .map(([name, count]) => ({ name, count, pct: Math.round((count / total) * 100) }));
}

export const LAYER_LABEL = { json_ld: "structured data", markup: "page markup", meta: "meta tags" };
