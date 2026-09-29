const KEYS = {
  users: "pw_mock_users",
  currentUserId: "pw_mock_current_user_id",
  products: "pw_mock_products",
  history: "pw_mock_history",
};

function read(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function write(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

export const store = {
  getUsers: () => read(KEYS.users, []),
  setUsers: (users) => write(KEYS.users, users),

  getCurrentUserId: () => localStorage.getItem(KEYS.currentUserId),
  setCurrentUserId: (id) => localStorage.setItem(KEYS.currentUserId, id),
  clearCurrentUserId: () => localStorage.removeItem(KEYS.currentUserId),

  getProducts: () => read(KEYS.products, null),
  setProducts: (products) => write(KEYS.products, products),

  getHistory: () => read(KEYS.history, null),
  setHistory: (history) => write(KEYS.history, history),
};

export function uuid() {
  return crypto.randomUUID();
}

/** Simula latência de rede, pra a UI de loading fazer sentido durante os testes de UX. */
export function delay(ms = 350) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
