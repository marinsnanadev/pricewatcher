import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { BASE_URL, getToken } from "../api.js";
import { useAuth } from "../auth/AuthContext.jsx";
import { formatPrice } from "../lib/format.js";
import { createRealtimeClient, toWsUrl } from "./client.js";

const RealtimeContext = createContext(null);

const TOAST_MS = 10_000;

const REASON_TEXT = {
  target_reached: "reached your target",
  further_drop: "dropped even further",
};

export function RealtimeProvider({ children }) {
  const { user } = useAuth();
  const userId = user?.id;

  const [status, setStatus] = useState("closed");
  const [epoch, setEpoch] = useState(0); // +1 on every RE-connection (see below)
  const [toasts, setToasts] = useState([]);
  const listeners = useRef(new Set());
  const toastTimers = useRef(new Map());
  const everLive = useRef(false);

  const subscribe = useCallback((fn) => {
    listeners.current.add(fn);
    return () => listeners.current.delete(fn);
  }, []);

  const dismissToast = useCallback((id) => {
    clearTimeout(toastTimers.current.get(id));
    toastTimers.current.delete(id);
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  const pushToast = useCallback(
    (data) => {
      const id = `${data.product_id}-${Date.now()}`;
      setToasts((list) => [...list.slice(-2), { id, ...data }]); // at most 3 on screen
      toastTimers.current.set(id, setTimeout(() => dismissToast(id), TOAST_MS));
    },
    [dismissToast]
  );

  useEffect(() => {
    if (!userId) return;
    everLive.current = false;

    const client = createRealtimeClient({
      url: toWsUrl(BASE_URL),
      getToken,
      onStatus: setStatus,
      onReady: () => {
        // Events are live-only: anything that happened while we were offline is gone.
        // So after a RE-connection, pages refetch from the REST API (they watch `epoch`).
        if (everLive.current) setEpoch((n) => n + 1);
        everLive.current = true;
      },
      onEvent: (event) => {
        listeners.current.forEach((fn) => fn(event));
        if (event.type === "alert.triggered") pushToast(event.data);
      },
    });
    client.start();

    const timers = toastTimers.current;
    return () => {
      client.stop();
      timers.forEach(clearTimeout);
      timers.clear();
      setToasts([]);
    };
  }, [userId, pushToast]);

  const value = useMemo(() => ({ status, epoch, subscribe }), [status, epoch, subscribe]);

  return (
    <RealtimeContext.Provider value={value}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="toast">
            <Link to={`/products/${t.product_id}`} onClick={() => dismissToast(t.id)}>
              <strong>{t.product_name}</strong> {REASON_TEXT[t.reason] ?? "has a new price"}
              <span className="toast-price mono">{formatPrice(t.price)}</span>
            </Link>
            <button type="button" className="toast-close" aria-label="Dismiss" onClick={() => dismissToast(t.id)}>
              ×
            </button>
          </div>
        ))}
      </div>
    </RealtimeContext.Provider>
  );
}

function useRealtime() {
  const ctx = useContext(RealtimeContext);
  if (!ctx) throw new Error("useRealtime* must be used inside <RealtimeProvider>");
  return ctx;
}

/** Connection state, plus `epoch`, which changes after every re-connection (refetch on it). */
export function useRealtimeStatus() {
  const { status, epoch } = useRealtime();
  return { status, epoch };
}

/** Calls handler(data, event) for every live event of this type. Latest handler is always used. */
export function useRealtimeEvent(type, handler) {
  const { subscribe } = useRealtime();
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(
    () =>
      subscribe((event) => {
        if (event.type === type) handlerRef.current(event.data, event);
      }),
    [subscribe, type]
  );
}
