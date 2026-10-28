import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import LiveBadge from "../components/LiveBadge.jsx";
import { formatDateTime, storeLabel } from "../lib/format.js";
import {
  LAYER_LABEL,
  diagnosisText,
  healthInfo,
  layerShares,
  msText,
  percentText,
} from "../lib/insights.js";

const REFRESH_MS = 30_000;

function StoreCard({ store }) {
  const meta = healthInfo(store.status);
  const diagnosis = diagnosisText(store.diagnosis);
  const shares = layerShares(store.layers);
  const errors = Object.entries(store.errors);

  return (
    <div className="panel">
      <div className="row store-head">
        <h2>{storeLabel(store.store)}</h2>
        <span className={`chip chip-${meta.tone}`}>{meta.label}</span>
      </div>

      <div className="ticker-row-prices mono">
        <span>{percentText(store.success_rate)} success</span>
        <span>{store.successes}/{store.attempts} checks</span>
        <span className="muted">p50 {msText(store.p50_ms)} · p95 {msText(store.p95_ms)}</span>
      </div>

      {diagnosis && <p className="error">{diagnosis}</p>}

      {shares.length > 0 && (
        <>
          <p className="muted store-sub">How prices were found</p>
          <div className="layer-bar" role="img" aria-label={shares.map((s) => `${s.pct}% ${LAYER_LABEL[s.name] ?? s.name}`).join(", ")}>
            {shares.map((s, i) => (
              <span key={s.name} className={`layer-seg layer-${i % 3}`} style={{ width: `${s.pct}%` }} />
            ))}
          </div>
          <p className="muted mono">
            {shares.map((s) => `${s.pct}% ${LAYER_LABEL[s.name] ?? s.name}`).join(" · ")}
          </p>
        </>
      )}

      {errors.length > 0 && (
        <p className="muted mono">Errors: {errors.map(([type, n]) => `${type} ×${n}`).join(", ")}</p>
      )}

      <p className="muted mono">
        Last success {formatDateTime(store.last_success_at)}
        {store.last_failure_at && <> · last failure {formatDateTime(store.last_failure_at)}</>}
      </p>
    </div>
  );
}

export default function StatusPage() {
  const [stores, setStores] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .getStoreHealth()
        .then((list) => !cancelled && (setStores(list), setError("")))
        .catch((err) => !cancelled && setError(err.message || "Could not load store status"));
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="container">
      <div className="topbar">
        <Link to="/" className="muted">Back to products</Link>
        <LiveBadge />
      </div>

      <h1>Store status</h1>
      <p className="muted">
        Whether the scrapers are working, based on every check in the last 24 hours. Updates every 30 seconds.
      </p>

      {error && <p className="error" role="alert">{error}</p>}
      {!error && stores === null && <p className="muted">Loading…</p>}
      {stores?.length === 0 && <p className="muted">No checks in the last 24 hours.</p>}
      {stores?.map((store) => (
        <StoreCard key={store.store} store={store} />
      ))}
    </div>
  );
}
