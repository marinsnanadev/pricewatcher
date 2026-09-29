import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import PriceChart from "../components/PriceChart.jsx";
import { formatDate, formatPrice, percentChange, storeLabel } from "../lib/format.js";

export default function ProductPage() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [product, setProduct] = useState(null);
  const [history, setHistory] = useState([]);
  const [targetInput, setTargetInput] = useState("");
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(""); // which action is running: "simulate" | "save" | "toggle" | "delete"
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const load = useCallback(async () => {
    const [p, h] = await Promise.all([api.getProduct(id), api.getHistory(id)]);
    setProduct(p);
    setHistory(h);
    setTargetInput(p.target_price != null ? String(p.target_price) : "");
  }, [id]);

  useEffect(() => {
    load().catch((err) => setLoadError(err.message || "Could not load this product"));
  }, [load]);

  // Runs one action, keeps the page in sync afterwards and surfaces any error.
  async function run(name, action) {
    setActionError("");
    setBusy(name);
    try {
      await action();
    } catch (err) {
      setActionError(err.message || "Something went wrong. Try again.");
    } finally {
      setBusy("");
    }
  }

  const simulate = () =>
    run("simulate", async () => {
      await api.simulatePriceCheck(id);
      await load();
    });

  const saveTarget = (e) => {
    e.preventDefault();
    let value = null;
    if (targetInput.trim() !== "") {
      value = Number(targetInput);
      if (!Number.isFinite(value) || value <= 0) {
        return setActionError("Target price must be greater than zero");
      }
    }
    run("save", async () => {
      await api.updateProduct(id, { target_price: value });
      await load();
    });
  };

  const toggleActive = () =>
    run("toggle", async () => {
      await api.updateProduct(id, { active: !product.active });
      await load();
    });

  const remove = () =>
    run("delete", async () => {
      await api.deleteProduct(id);
      navigate("/", { replace: true });
    });

  if (loadError) {
    return (
      <div className="container">
        <Link to="/" className="muted">Back to products</Link>
        <p className="error" role="alert">{loadError}</p>
      </div>
    );
  }
  if (!product) {
    return (
      <div className="container">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  const { name, url, store, current_price, target_price, active, last_error } = product;
  const belowTarget = target_price != null && current_price <= target_price;
  const change = percentChange(current_price, history.at(-2)?.price);
  const lowest = history.length ? Math.min(...history.map((h) => h.price)) : null;

  return (
    <div className="container">
      <div className="topbar">
        <Link to="/" className="muted">Back to products</Link>
      </div>

      <h1>{name}</h1>
      <p className="muted">
        {storeLabel(store)}
        {!active && " (paused)"} ·{" "}
        <a href={url} target="_blank" rel="noopener noreferrer">Open product page</a>
      </p>

      <div className="panel">
        <div className="price-with-delta">
          <span className={`price ${belowTarget ? "below-target" : ""}`}>
            {formatPrice(current_price)}
          </span>
          {change != null && (
            <span className={`delta ${change < 0 ? "down" : "up"}`}>
              {change > 0 ? "+" : "-"}
              {Math.abs(change).toFixed(1)}%
            </span>
          )}
        </div>
        {target_price != null && (
          <p className="price-target">
            {belowTarget ? "At or below your target of " : "Target "}
            {formatPrice(target_price)}
          </p>
        )}
        {last_error && <p className="error">{last_error}</p>}

        <PriceChart points={history} target={target_price} />

        {history.length > 0 && (
          <div className="ticker-row-prices muted mono">
            <span>{formatDate(history[0].collected_at)}</span>
            <span>Lowest {formatPrice(lowest)}</span>
            <span>{formatDate(history[history.length - 1].collected_at)}</span>
          </div>
        )}
      </div>

      <div className="mock-banner">
        Mock mode: simulates one scheduler cycle and moves the price up or down.
      </div>
      <div className="row" style={{ marginBottom: 20 }}>
        <button type="button" className="secondary" onClick={simulate} disabled={busy !== ""}>
          {busy === "simulate" ? "Checking…" : "Simulate a price check"}
        </button>
      </div>

      <form className="panel" onSubmit={saveTarget} noValidate>
        <h2>Alert settings</h2>
        <label htmlFor="target">Alert me when the price drops to</label>
        <input
          id="target"
          type="number"
          inputMode="decimal"
          min="0"
          step="0.01"
          placeholder="No target set"
          value={targetInput}
          onChange={(e) => setTargetInput(e.target.value)}
        />
        <div className="row">
          <button type="submit" disabled={busy !== ""}>
            {busy === "save" ? "Saving…" : "Save target"}
          </button>
          <button type="button" className="secondary" onClick={toggleActive} disabled={busy !== ""}>
            {active ? "Pause tracking" : "Resume tracking"}
          </button>
        </div>
      </form>

      {actionError && <p className="error" role="alert">{actionError}</p>}

      <div className="panel">
        <h2>Delete product</h2>
        <p className="muted">This removes the product and its price history.</p>
        {confirmingDelete ? (
          <div className="row">
            <button type="button" className="danger" onClick={remove} disabled={busy !== ""}>
              {busy === "delete" ? "Deleting…" : "Yes, delete it"}
            </button>
            <button type="button" className="secondary" onClick={() => setConfirmingDelete(false)}>
              Keep it
            </button>
          </div>
        ) : (
          <button type="button" className="danger" onClick={() => setConfirmingDelete(true)}>
            Delete product
          </button>
        )}
      </div>
    </div>
  );
}
