import { Link } from "react-router-dom";
import { formatPrice, percentChange, storeLabel } from "../lib/format.js";

export default function TickerRow({ product }) {
  const { id, name, store, current_price, target_price, previousPrice, active, last_error, flash, flashKey } = product;

  const belowTarget = target_price != null && current_price <= target_price;
  const change = percentChange(current_price, previousPrice);

  return (
    <Link
      to={`/products/${id}`}
      className={`ticker-row ${belowTarget ? "status-below-target" : "status-tracking"}`}
    >
      <div className="ticker-row-name">{name}</div>
      <div className="ticker-row-meta">
        {storeLabel(store)}
        {!active && " (paused)"}
      </div>

      <div className="ticker-row-prices">
        <div className="price-with-delta">
          {/* new key on every live price change, so the highlight animation replays */}
          <span
            key={flashKey ?? 0}
            className={`price ${belowTarget ? "below-target" : ""} ${flash ? `flash-${flash}` : ""}`}
          >
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
          <span className="price-target">Target {formatPrice(target_price)}</span>
        )}
      </div>

      {last_error && <p className="error">{last_error}</p>}
    </Link>
  );
}
