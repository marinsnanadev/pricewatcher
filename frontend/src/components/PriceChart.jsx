import { formatPrice } from "../lib/format.js";

const W = 600;
const H = 140;
const PAD_Y = 14;

/**
 * Hand-rolled SVG line chart (no chart lib). The viewBox stretches to fit the
 * container, so strokes use non-scaling-stroke to stay crisp, and the latest
 * point is a zero-length round-capped line (a circle would get squashed).
 */
export default function PriceChart({ points, target }) {
  if (!points.length) return null;

  const times = points.map((p) => new Date(p.collected_at).getTime());
  const prices = points.map((p) => p.price);
  const scaleValues = target != null ? [...prices, target] : prices;

  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const pMin = Math.min(...scaleValues);
  const pMax = Math.max(...scaleValues);

  const x = (t) => (tMax === tMin ? W / 2 : ((t - tMin) / (tMax - tMin)) * W);
  const y = (v) =>
    pMax === pMin ? H / 2 : PAD_Y + (1 - (v - pMin) / (pMax - pMin)) * (H - PAD_Y * 2);

  const coords = points.map((p, i) => [x(times[i]), y(p.price)]);
  const last = coords[coords.length - 1];
  const belowTarget = target != null && prices[prices.length - 1] <= target;

  const label =
    `Price history: ${points.length} checks, from ${formatPrice(prices[0])} ` +
    `to ${formatPrice(prices[prices.length - 1])}` +
    (target != null ? `, target ${formatPrice(target)}` : "");

  return (
    <svg
      className="history-chart"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
    >
      {target != null && (
        <line
          x1="0"
          x2={W}
          y1={y(target)}
          y2={y(target)}
          strokeDasharray="4 4"
          vectorEffect="non-scaling-stroke"
          style={{ stroke: "var(--drop)", strokeWidth: 1 }}
        />
      )}
      {coords.length > 1 && (
        <polyline
          points={coords.map((c) => c.join(",")).join(" ")}
          fill="none"
          vectorEffect="non-scaling-stroke"
          style={{ stroke: "var(--accent)", strokeWidth: 2, strokeLinejoin: "round" }}
        />
      )}
      <line
        x1={last[0]}
        x2={last[0]}
        y1={last[1]}
        y2={last[1]}
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
        style={{ stroke: belowTarget ? "var(--drop)" : "var(--accent-strong)", strokeWidth: 8 }}
      />
    </svg>
  );
}
