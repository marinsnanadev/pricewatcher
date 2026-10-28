import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { formatPrice } from "../lib/format.js";
import { FLAG_TEXT, SOURCE_LABEL, actionInfo, dealInfo, discountText } from "../lib/insights.js";
import { useRealtimeEvent, useRealtimeStatus } from "../realtime/RealtimeContext.jsx";

export default function InsightsPanel({ productId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const { epoch } = useRealtimeStatus();
  const timer = useRef(null);

  const load = useCallback(
    async (refresh = false) => {
      try {
        setData(await api.getInsights(productId, { refresh }));
        setError("");
      } catch (err) {
        setError(err.message || "Could not load the deal check");
      }
    },
    [productId]
  );

  useEffect(() => {
    load();
  }, [load, epoch]);

  useEffect(() => () => clearTimeout(timer.current), []);

  // a new price just came in: re-run the (cheap, cached) analysis shortly after
  useRealtimeEvent("product.checked", (event) => {
    if (event.product_id !== productId || event.status !== "success") return;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => load(), 1000);
  });

  async function refresh() {
    setRefreshing(true);
    await load(true);
    setRefreshing(false);
  }

  if (error && !data) {
    return (
      <div className="panel">
        <h2>Deal check</h2>
        <p className="error" role="alert">{error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="panel">
        <h2>Deal check</h2>
        <p className="muted">Analyzing price history…</p>
      </div>
    );
  }

  const { deal, verdict, stats } = data;
  const dealMeta = dealInfo(deal.verdict);
  const action = actionInfo(verdict.action);
  const hasAnalysis = deal.verdict !== "insufficient_data";

  return (
    <div className="panel">
      <h2>Deal check</h2>

      <p>
        <span className={`chip chip-${dealMeta.tone}`}>{dealMeta.label}</span>
      </p>

      {deal.claimed_discount_pct != null && (
        <p className="mono">
          Advertised {discountText(deal.claimed_discount_pct)}
          {hasAnalysis && <> · actually {discountText(deal.real_discount_pct)} vs. its usual {formatPrice(deal.reference_price)}</>}
        </p>
      )}
      {deal.claimed_discount_pct == null && hasAnalysis && (
        <p className="mono">
          {discountText(deal.real_discount_pct)} vs. its usual price of {formatPrice(deal.reference_price)}
        </p>
      )}
      {!hasAnalysis && (
        <p className="muted">
          We've tracked this product for {deal.days_tracked} days ({deal.data_points} checks). We need about a week of
          history before we can tell whether a discount is real.
        </p>
      )}

      {deal.flags.length > 0 && (
        <ul className="flag-list">
          {deal.flags.map((flag) => (
            <li key={flag}>{FLAG_TEXT[flag] ?? flag}</li>
          ))}
        </ul>
      )}

      {hasAnalysis && (
        <div className="ticker-row-prices muted mono">
          <span>Lowest {formatPrice(stats.lowest_price)}</span>
          <span>Usual {formatPrice(deal.reference_price)}</span>
          <span>Highest {formatPrice(stats.highest_price)}</span>
        </div>
      )}

      <h2 className="verdict-title">Should you buy?</h2>
      <div className={`verdict verdict-${action.tone}`}>
        <div className="row">
          <strong>{action.label}</strong>
          <span className="muted mono">
            {Math.round(verdict.confidence * 100)}% sure · {SOURCE_LABEL[verdict.source] ?? verdict.source}
          </span>
        </div>
        <p>{verdict.reasoning}</p>
      </div>

      <div className="row check-row">
        <button type="button" className="secondary" onClick={refresh} disabled={refreshing}>
          {refreshing ? "Thinking…" : "Refresh verdict"}
        </button>
        <span className="muted mono">
          {deal.confidence} confidence · {deal.data_points} checks over {deal.days_tracked} days
          {data.cached ? " · cached" : ""}
        </span>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}
