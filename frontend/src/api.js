// Real API client (FastAPI backend). Replaces the old localStorage mock.
//
// The backend URL comes from VITE_API_URL (e.g. in frontend/.env.local);
// it defaults to the local dev server, which already allows this origin via CORS.
export const BASE_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/+$/, "");

const TOKEN_KEY = "pw_token";

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore: storage unavailable
  }
}

// FastAPI errors come as {detail: "text"} or, for validation errors, {detail: [{msg, ...}]}.
function errorMessage(data, status) {
  const detail = data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d) => (d.msg || "").replace(/^Value error, /, ""))
      .filter(Boolean)
      .join(". ");
  }
  return `Request failed (${status})`;
}

async function request(path, { method = "GET", body, form, auth = true } = {}) {
  const headers = {};
  let payload;

  if (form) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    payload = new URLSearchParams(form);
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  if (auth) {
    const token = getToken();
    if (!token) throw new Error("Not authenticated");
    headers.Authorization = `Bearer ${token}`;
  }

  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, { method, headers, body: payload });
  } catch {
    throw new Error("Could not reach the server. Is the backend running?");
  }

  if (res.status === 204) return null;

  let data = null;
  try {
    data = await res.json();
  } catch {
    // non-JSON response; handled below
  }

  if (!res.ok) {
    if (res.status === 401 && auth) {
      clearToken();
      throw new Error("Your session expired. Sign in again.");
    }
    throw new Error(errorMessage(data, res.status));
  }
  return data;
}

export const api = {
  register(email, password) {
    return request("/auth/register", {
      method: "POST",
      body: { email: (email || "").trim(), password },
      auth: false,
    });
  },

  async login(email, password) {
    // the API uses the OAuth2 password form, where "username" is the email
    const data = await request("/auth/login", {
      method: "POST",
      form: { username: (email || "").trim(), password },
      auth: false,
    });
    setToken(data.access_token);
    return data;
  },

  me() {
    return request("/auth/me");
  },

  listProducts() {
    return request("/products");
  },

  // The backend scrapes the page before answering, so this call can take a few seconds.
  createProduct(url, targetPrice) {
    return request("/products", {
      method: "POST",
      body: { url, target_price: targetPrice ?? null },
    });
  },

  getProduct(id) {
    return request(`/products/${id}`);
  },

  updateProduct(id, payload) {
    return request(`/products/${id}`, { method: "PATCH", body: payload });
  },

  deleteProduct(id) {
    return request(`/products/${id}`, { method: "DELETE" });
  },

  getHistory(id) {
    return request(`/products/${id}/history`);
  },

  // Queues a check right now; the worker answers through the live connection.
  checkNow(id) {
    return request(`/products/${id}/check`, { method: "POST" });
  },
};
