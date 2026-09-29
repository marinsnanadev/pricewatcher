import { store, uuid, delay } from "./mock/mockStore.js";
import { fakeScrape, fluctuate } from "./mock/mockScraper.js";
import { seedIfEmpty } from "./mock/seed.js";

export function getToken() {
  return store.getCurrentUserId();
}

export function clearToken() {
  store.clearCurrentUserId();
}

function requireAuth() {
  const userId = store.getCurrentUserId();
  if (!userId) throw new Error("Not authenticated");
  return userId;
}

function findProduct(id, userId) {
  const product = (store.getProducts() || []).find(
    (p) => p.id === id && p.user_id === userId
  );
  if (!product) throw new Error("Product not found");
  return product;
}

export const api = {
  async register(email, password) {
    await delay();
    if (!email || !email.includes("@")) throw new Error("Invalid email");
    if (!password || password.length < 8) {
      throw new Error("Password must be at least 8 characters long");
    }
    const users = store.getUsers();
    if (users.some((u) => u.email === email)) {
      throw new Error("Email already registered");
    }
    const user = { id: uuid(), email, password, created_at: new Date().toISOString() };
    store.setUsers([...users, user]);
    return { id: user.id, email: user.email, created_at: user.created_at };
  },

  async login(email, password) {
    await delay();
    const user = store.getUsers().find((u) => u.email === email);
    if (!user || user.password !== password) {
      throw new Error("Invalid email or password");
    }
    store.setCurrentUserId(user.id);
    seedIfEmpty(user.id);
    return { access_token: user.id, token_type: "bearer" };
  },

  async me() {
    await delay();
    const userId = requireAuth();
    const user = store.getUsers().find((u) => u.id === userId);
    if (!user) throw new Error("User not found");
    return { id: user.id, email: user.email, created_at: user.created_at };
  },

  async listProducts() {
    await delay();
    const userId = requireAuth();
    return (store.getProducts() || []).filter((p) => p.user_id === userId);
  },

  async createProduct(url, targetPrice) {
    await delay(600); // "scraping" is deliberately slower than other calls
    const userId = requireAuth();
    if (!url || !url.trim()) throw new Error("Enter the product URL");

    const scraped = fakeScrape(url);
    const product = {
      id: uuid(),
      user_id: userId,
      url,
      name: scraped.name,
      store: scraped.store,
      current_price: scraped.price,
      target_price: targetPrice ?? null,
      active: true,
      last_error: null,
      created_at: new Date().toISOString(),
    };

    store.setProducts([...(store.getProducts() || []), product]);
    store.setHistory([
      ...(store.getHistory() || []),
      { id: uuid(), product_id: product.id, price: scraped.price, collected_at: product.created_at },
    ]);

    return product;
  },

  async getProduct(id) {
    await delay();
    const userId = requireAuth();
    return findProduct(id, userId);
  },

  async updateProduct(id, payload) {
    await delay();
    const userId = requireAuth();
    const products = store.getProducts() || [];
    const index = products.findIndex((p) => p.id === id && p.user_id === userId);
    if (index === -1) throw new Error("Product not found");

    products[index] = { ...products[index], ...payload };
    store.setProducts(products);
    return products[index];
  },

  async deleteProduct(id) {
    await delay();
    const userId = requireAuth();
    store.setProducts(
      (store.getProducts() || []).filter((p) => !(p.id === id && p.user_id === userId))
    );
    store.setHistory((store.getHistory() || []).filter((h) => h.product_id !== id));
    return null;
  },

  async getHistory(id) {
    await delay();
    const userId = requireAuth();
    findProduct(id, userId); // validates ownership/existence
    return (store.getHistory() || [])
      .filter((h) => h.product_id === id)
      .sort((a, b) => new Date(a.collected_at) - new Date(b.collected_at));
  },

  /**
   * Mock-only helper: simulates "one scheduler cycle" for a product,
   * nudging its price up or down. Useful for visually testing what happens
   * when a price drops below the target. The product page exposes a
   * button for this — it won't exist once this file is wired to the real
   * API, since that check runs server-side on a timer instead.
   */
  async simulatePriceCheck(id) {
    await delay(500);
    const userId = requireAuth();
    const product = findProduct(id, userId);
    const newPrice = fluctuate(product.current_price);

    const products = store.getProducts().map((p) =>
      p.id === id ? { ...p, current_price: newPrice, last_error: null } : p
    );
    store.setProducts(products);
    store.setHistory([
      ...(store.getHistory() || []),
      { id: uuid(), product_id: id, price: newPrice, collected_at: new Date().toISOString() },
    ]);

    return products.find((p) => p.id === id);
  },
};
