import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useAuth } from "../auth/AuthContext.jsx";
import ProductForm from "../components/ProductForm.jsx";
import TickerRow from "../components/TickerRow.jsx";

// Products plus the price from the check before the latest one (for the % change).
async function loadProducts() {
  const list = await api.listProducts();
  const histories = await Promise.all(list.map((p) => api.getHistory(p.id)));
  return list
    .map((p, i) => ({ ...p, previousPrice: histories[i].at(-2)?.price ?? null }))
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
}

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const [products, setProducts] = useState(null); // null = still loading
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    loadProducts()
      .then((list) => !cancelled && setProducts(list))
      .catch((err) => !cancelled && setError(err.message || "Could not load your products"));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="container">
      <div className="topbar">
        <h1>Price Watcher</h1>
        <div className="row">
          <span className="muted mono">{user.email}</span>
          <button type="button" className="secondary" onClick={logout}>
            Sign out
          </button>
        </div>
      </div>

      <ProductForm onCreated={(product) => setProducts((prev) => [product, ...(prev ?? [])])} />

      <h2>Your products</h2>

      {error && <p className="error" role="alert">{error}</p>}
      {!error && products === null && <p className="muted">Loading…</p>}
      {products?.length === 0 && (
        <p className="muted">Nothing tracked yet. Paste a product link above to start.</p>
      )}
      {products?.map((product) => (
        <TickerRow key={product.id} product={product} />
      ))}
    </div>
  );
}
