import { useState } from "react";
import { api } from "../api.js";

function isHttpUrl(value) {
  try {
    const { protocol } = new URL(value);
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

export default function ProductForm({ onCreated }) {
  const [url, setUrl] = useState("");
  const [target, setTarget] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    const cleanUrl = url.trim();
    if (!isHttpUrl(cleanUrl)) return setError("Enter a full product link, starting with https://");

    let targetPrice = null;
    if (target.trim() !== "") {
      targetPrice = Number(target);
      if (!Number.isFinite(targetPrice) || targetPrice <= 0) {
        return setError("Target price must be greater than zero");
      }
    }

    setSubmitting(true);
    try {
      const product = await api.createProduct(cleanUrl, targetPrice);
      setUrl("");
      setTarget("");
      onCreated({ ...product, previousPrice: null });
    } catch (err) {
      setError(err.message || "Could not add this product. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="panel" onSubmit={handleSubmit} noValidate>
      <h2>Track a product</h2>

      <label htmlFor="product-url">Product link</label>
      <input
        id="product-url"
        type="url"
        placeholder="https://www.mercadolivre.com.br/..."
        value={url}
        onChange={(e) => setUrl(e.target.value)}
      />

      <label htmlFor="target-price">Alert me when the price drops to (optional)</label>
      <input
        id="target-price"
        type="number"
        inputMode="decimal"
        min="0"
        step="0.01"
        placeholder="199.90"
        value={target}
        onChange={(e) => setTarget(e.target.value)}
      />

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <button type="submit" disabled={submitting}>
        {submitting ? "Checking the price…" : "Start tracking"}
      </button>
    </form>
  );
}
