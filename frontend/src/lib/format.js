// Single place to change currency/locale later (the mock has no currency field yet).
const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

export function formatPrice(value) {
  return money.format(value);
}

const STORE_LABELS = {
  mercado_livre: "Mercado Livre",
  amazon: "Amazon",
  unknown_store: "Unknown store",
};

export function storeLabel(store) {
  return STORE_LABELS[store] ?? store;
}

/** Percent change from `previous` to `current`, e.g. -4.2. Null if there's nothing to compare. */
export function percentChange(current, previous) {
  if (previous == null || previous === 0 || current === previous) return null;
  return ((current - previous) / previous) * 100;
}

const dateFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });

export function formatDate(iso) {
  return dateFmt.format(new Date(iso));
}
