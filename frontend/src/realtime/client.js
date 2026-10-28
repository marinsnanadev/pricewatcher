// WebSocket client with auto-reconnect. Plain JS with injectable dependencies
// (WebSocket, timers, random) so it can be tested without a browser.
//
// Protocol (see backend/app/routers/realtime.py):
//   -> {"type":"auth","token":"<jwt>"}     first message after the socket opens
//   <- {"type":"ready"}                    we're subscribed; everything from now on arrives
//   <- {"type":"product.checked"|"alert.triggered", "data":{...}}
//   <- {"type":"heartbeat"}                server keep-alive when idle
//   -> "ping"  /  <- {"type":"pong"}
//   close code 4401 = auth failed: don't retry, the user has to sign in again

export const UNAUTHORIZED = 4401;
const PING_MS = 25_000;
const STALE_MS = 70_000; // heartbeats come every ~25s; silence this long means a dead link
const BACKOFF_BASE_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;

export function toWsUrl(httpUrl) {
  return httpUrl.replace(/\/+$/, "").replace(/^http/, "ws") + "/ws";
}

export function createRealtimeClient({
  url,
  getToken,
  onEvent,
  onStatus,
  onReady,
  WebSocketImpl = globalThis.WebSocket,
  timers = globalThis,
  random = Math.random,
}) {
  let socket = null;
  let stopped = true;
  let attempt = 0;
  let status = "closed";
  let retryTimer = null;
  let pingTimer = null;
  let staleTimer = null;

  function setStatus(next) {
    if (next !== status) {
      status = next;
      onStatus?.(next);
    }
  }

  function clearSocketTimers() {
    timers.clearInterval(pingTimer);
    timers.clearTimeout(staleTimer);
    pingTimer = staleTimer = null;
  }

  function armStaleTimer(forSocket) {
    timers.clearTimeout(staleTimer);
    staleTimer = timers.setTimeout(() => {
      try {
        forSocket.close();
      } catch {
        // already gone
      }
      handleClosed(forSocket, 4000); // don't wait for a close event a dead link may never send
    }, STALE_MS);
  }

  function scheduleReconnect() {
    setStatus("reconnecting");
    // exponential backoff with jitter, so a server restart doesn't get a thundering herd
    const delay = Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** attempt) * (0.5 + random() * 0.5);
    attempt += 1;
    retryTimer = timers.setTimeout(connect, delay);
  }

  function handleClosed(closedSocket, code) {
    if (socket !== closedSocket) return; // an old socket; we've already moved on
    socket = null;
    clearSocketTimers();
    if (stopped) return;
    if (code === UNAUTHORIZED) {
      setStatus("unauthorized");
      return;
    }
    scheduleReconnect();
  }

  function connect() {
    retryTimer = null;
    if (stopped) return;
    const token = getToken();
    if (!token) {
      setStatus("unauthorized");
      return;
    }
    setStatus(attempt === 0 ? "connecting" : "reconnecting");

    const current = new WebSocketImpl(url);
    socket = current;

    current.onopen = () => current.send(JSON.stringify({ type: "auth", token }));

    current.onmessage = (event) => {
      if (socket !== current) return;
      armStaleTimer(current);
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (!message || typeof message.type !== "string") return;

      if (message.type === "ready") {
        attempt = 0;
        timers.clearInterval(pingTimer);
        pingTimer = timers.setInterval(() => current.send("ping"), PING_MS);
        setStatus("live");
        onReady?.();
      } else if (message.type !== "pong" && message.type !== "heartbeat") {
        onEvent?.(message);
      }
    };

    current.onclose = (event) => handleClosed(current, event?.code);
    current.onerror = () => {}; // a close event always follows; reconnect logic lives there
    armStaleTimer(current);
  }

  return {
    start() {
      if (!stopped) return;
      stopped = false;
      attempt = 0;
      connect();
    },
    stop() {
      stopped = true;
      timers.clearTimeout(retryTimer);
      retryTimer = null;
      clearSocketTimers();
      const current = socket;
      socket = null;
      try {
        current?.close();
      } catch {
        // already gone
      }
      setStatus("closed");
    },
    get status() {
      return status;
    },
  };
}
