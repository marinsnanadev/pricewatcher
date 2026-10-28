import { useRealtimeStatus } from "../realtime/RealtimeContext.jsx";

const LABELS = {
  live: "Live",
  connecting: "Connecting…",
  reconnecting: "Reconnecting…",
  unauthorized: "Offline",
  closed: "Offline",
};

export default function LiveBadge() {
  const { status } = useRealtimeStatus();
  return (
    <span
      className={`live-badge live-${status}`}
      title={status === "live" ? "Prices update here as soon as they're checked" : "Live updates are not connected"}
    >
      <span className="live-dot" aria-hidden="true" />
      {LABELS[status] ?? "Offline"}
    </span>
  );
}
