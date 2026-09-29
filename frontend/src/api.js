import { store, uuid, delay } from "./mock/mockStore.js";
import { fakeScrape, fluctuate } from "./mock/mockScraper.js";
import { seedIfEmpty } from "./mock/seed.js";

const TOKEN_KEY = "pw_mock_token"; // mantém o mesmo nome de conceito da versão real

export function getToken() {
  return store.getCurrentUserId();
}

export function clearToken() {
  store.clearCurrentUserId();
}

function requireAuth() {
  const userId = store.getCurrentUserId();
  if (!userId) throw new Error("Não autenticado");
  return userId;
}

function findProduct(id, userId) {
  const product = (store.getProducts() || []).find(
    (p) => p.id === id && p.user_id === userId
  );
  if (!product) throw new Error("Produto não encontrado");
  return product;
}

export const api = {
  async register(email, password) {
    await delay();
    if (!email || !email.includes("@")) throw new Error("E-mail inválido");
    if (!password || password.length < 8) {
      throw new Error("A senha precisa ter pelo menos 8 caracteres");
    }
    const users = store.getUsers();
    if (users.some((u) => u.email === email)) {
      throw new Error("E-mail já cadastrado");
    }
    const user = { id: uuid(), email, password, created_at: new Date().toISOString() };
    store.setUsers([...users, user]);
    return { id: user.id, email: user.email, created_at: user.created_at };
  },

  async login(email, password) {
    await delay();
    const user = store.getUsers().find((u) => u.email === email);
    if (!user || user.password !== password) {
      throw new Error("E-mail ou senha inválidos");
    }
    store.setCurrentUserId(user.id);
    seedIfEmpty(user.id);
    return { access_token: user.id, token_type: "bearer" };
  },

  async me() {
    await delay();
    const userId = requireAuth();
    const user = store.getUsers().find((u) => u.id === userId);
    if (!user) throw new Error("Usuário não encontrado");
    return { id: user.id, email: user.email, created_at: user.created_at };
  },

  async listProducts() {
    await delay();
    const userId = requireAuth();
    return (store.getProducts() || []).filter((p) => p.user_id === userId);
  },

  async createProduct(url, targetPrice) {
    await delay(600); // "scraping" demora um pouco mais, de propósito
    const userId = requireAuth();
    if (!url || !url.trim()) throw new Error("Informe a URL do produto");

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
    if (index === -1) throw new Error("Produto não encontrado");

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
    findProduct(id, userId); // valida posse/existência
    return (store.getHistory() || [])
      .filter((h) => h.product_id === id)
      .sort((a, b) => new Date(a.collected_at) - new Date(b.collected_at));
  },

  /**
   * Só existe no mock: simula "passar um ciclo do scheduler" pra um
   * produto, variando o preço. Útil pra testar visualmente o que acontece
   * quando o preço cai abaixo do alvo. A tela de produto expõe um botão
   * pra isso — não existirá na versão conectada à API real.
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
