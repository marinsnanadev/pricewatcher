import { store, uuid } from "./mockStore.js";

function daysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString();
}

export function seedIfEmpty(userId) {
  if (store.getProducts() !== null) return;

  const productA = uuid();
  const productB = uuid();

  store.setProducts([
    {
      id: productA,
      user_id: userId,
      url: "https://www.mercadolivre.com.br/confort-run-sport-sneakers",
      name: "Confort Run Sport Sneakers",
      store: "mercado_livre",
      current_price: 249.9,
      target_price: 199.9,
      active: true,
      last_error: null,
      created_at: daysAgo(14),
    },
    {
      id: productB,
      user_id: userId,
      url: "https://www.amazon.com/xyz-bluetooth-headphones",
      name: "XYZ Bluetooth Headphones",
      store: "amazon",
      current_price: 179.0,
      target_price: 150.0,
      active: true,
      last_error: null,
      created_at: daysAgo(9),
    },
  ]);

  store.setHistory([
    { id: uuid(), product_id: productA, price: 299.9, collected_at: daysAgo(14) },
    { id: uuid(), product_id: productA, price: 289.9, collected_at: daysAgo(10) },
    { id: uuid(), product_id: productA, price: 269.9, collected_at: daysAgo(6) },
    { id: uuid(), product_id: productA, price: 259.9, collected_at: daysAgo(3) },
    { id: uuid(), product_id: productA, price: 249.9, collected_at: daysAgo(0) },

    { id: uuid(), product_id: productB, price: 199.0, collected_at: daysAgo(9) },
    { id: uuid(), product_id: productB, price: 195.0, collected_at: daysAgo(5) },
    { id: uuid(), product_id: productB, price: 179.0, collected_at: daysAgo(1) },
  ]);
}
