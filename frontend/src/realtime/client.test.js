import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";
import { createRealtimeClient, toWsUrl, UNAUTHORIZED } from "./client.js";

// --- test doubles -----------------------------------------------------------

class FakeSocket {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.sent = [];
    this.closed = false;
    FakeSocket.instances.push(this);
  }
  send(data) {
    this.sent.push(data);
  }
  close() {
    this.closed = true;
  }
  // helpers the tests use to play the server's part
  open() {
    this.onopen?.();
  }
  receive(message) {
    this.onmessage?.({ data: typeof message === "string" ? message : JSON.stringify(message) });
  }
  drop(code = 1006) {
    this.onclose?.({ code });
  }
}

class FakeTimers {
  now = 0;
  nextId = 1;
  items = new Map();
  setTimeout = (fn, ms) => this.#add(fn, ms, false);
  setInterval = (fn, ms) => this.#add(fn, ms, true);
  clearTimeout = (id) => this.items.delete(id);
  clearInterval = (id) => this.items.delete(id);
  #add(fn, ms, repeat) {
    const id = this.nextId++;
    this.items.set(id, { fn, at: this.now + ms, ms, repeat });
    return id;
  }
  advance(ms) {
    const target = this.now + ms;
    for (;;) {
      const due = [...this.items.entries()]
        .filter(([, t]) => t.at <= target)
        .sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      const [id, t] = due;
      this.now = t.at;
      if (t.repeat) t.at += t.ms;
      else this.items.delete(id);
      t.fn();
    }
    this.now = target;
  }
}

let timers;
let statuses;
let events;
let readies;
let token;

function makeClient(overrides = {}) {
  return createRealtimeClient({
    url: "ws://localhost:8000/ws",
    getToken: () => token,
    onStatus: (s) => statuses.push(s),
    onEvent: (e) => events.push(e),
    onReady: () => readies.push(1),
    WebSocketImpl: FakeSocket,
    timers,
    random: () => 1, // no jitter: delays are the exact backoff values
    ...overrides,
  });
}

const last = () => FakeSocket.instances.at(-1);

function connectAndGoLive(client) {
  client.start();
  last().open();
  last().receive({ type: "ready" });
}

beforeEach(() => {
  FakeSocket.instances = [];
  timers = new FakeTimers();
  statuses = [];
  events = [];
  readies = [];
  token = "jwt-123";
});

// --- tests -----------------------------------------------------------------

describe("toWsUrl", () => {
  it("swaps the scheme and appends /ws", () => {
    assert.equal(toWsUrl("http://localhost:8000"), "ws://localhost:8000/ws");
    assert.equal(toWsUrl("https://api.example.com/"), "wss://api.example.com/ws");
  });
});

describe("connecting", () => {
  it("authenticates with the token in the first message, not in the URL", () => {
    makeClient().start();
    assert.equal(last().url, "ws://localhost:8000/ws");
    last().open();
    assert.deepEqual(JSON.parse(last().sent[0]), { type: "auth", token: "jwt-123" });
  });

  it("goes connecting -> live only once the server says ready", () => {
    const client = makeClient();
    client.start();
    last().open();
    assert.deepEqual(statuses, ["connecting"]);
    last().receive({ type: "ready" });
    assert.deepEqual(statuses, ["connecting", "live"]);
    assert.equal(readies.length, 1);
  });

  it("without a token it never opens a socket", () => {
    token = null;
    makeClient().start();
    assert.equal(FakeSocket.instances.length, 0);
    assert.deepEqual(statuses, ["unauthorized"]);
  });
});

describe("messages", () => {
  it("delivers events and swallows pong, heartbeat and garbage", () => {
    connectAndGoLive(makeClient());
    last().receive({ type: "product.checked", data: { current_price: 80 } });
    last().receive({ type: "pong" });
    last().receive({ type: "heartbeat" });
    last().receive("not json");
    last().receive({ no: "type" });
    last().receive({ type: "alert.triggered", data: {} });
    assert.deepEqual(
      events.map((e) => e.type),
      ["product.checked", "alert.triggered"]
    );
  });

  it("pings every 25s while live", () => {
    connectAndGoLive(makeClient());
    timers.advance(24_999);
    assert.deepEqual(last().sent.filter((m) => m === "ping"), []);
    timers.advance(1);
    assert.equal(last().sent.filter((m) => m === "ping").length, 1);
    timers.advance(25_000);
    assert.equal(last().sent.filter((m) => m === "ping").length, 2);
  });
});

describe("reconnecting", () => {
  it("retries with exponential backoff, capped at 30s", () => {
    makeClient().start();
    const delays = [];
    for (let i = 0; i < 7; i++) {
      const before = FakeSocket.instances.length;
      last().drop();
      // find how long until the next socket appears
      let waited = 0;
      while (FakeSocket.instances.length === before) {
        timers.advance(500);
        waited += 500;
      }
      delays.push(waited);
    }
    assert.deepEqual(delays, [1000, 2000, 4000, 8000, 16000, 30000, 30000]);
  });

  it("reports reconnecting, then live again, and resets the backoff", () => {
    const client = makeClient();
    connectAndGoLive(client);
    last().drop();
    assert.equal(client.status, "reconnecting");
    timers.advance(1000);
    last().open();
    last().receive({ type: "ready" });
    assert.equal(client.status, "live");
    assert.equal(readies.length, 2);

    last().drop(); // next outage starts from 1s again
    const before = FakeSocket.instances.length;
    timers.advance(999);
    assert.equal(FakeSocket.instances.length, before);
    timers.advance(1);
    assert.equal(FakeSocket.instances.length, before + 1);
  });

  it("does not retry after an auth failure (4401)", () => {
    const client = makeClient();
    client.start();
    last().open();
    last().drop(UNAUTHORIZED);
    timers.advance(120_000);
    assert.equal(FakeSocket.instances.length, 1);
    assert.equal(client.status, "unauthorized");
  });

  it("treats a long silence as a dead link and reconnects", () => {
    const client = makeClient();
    connectAndGoLive(client);
    const first = last();
    timers.advance(69_999);
    assert.equal(FakeSocket.instances.length, 1);
    timers.advance(1);
    assert.equal(first.closed, true);
    assert.equal(client.status, "reconnecting");
    timers.advance(1000);
    assert.equal(FakeSocket.instances.length, 2);
  });

  it("any message (e.g. a heartbeat) keeps the link alive", () => {
    connectAndGoLive(makeClient());
    for (let i = 0; i < 6; i++) {
      timers.advance(25_000);
      last().receive({ type: "heartbeat" });
    }
    assert.equal(FakeSocket.instances.length, 1);
  });
});

describe("stop", () => {
  it("closes the socket and never reconnects", () => {
    const client = makeClient();
    connectAndGoLive(client);
    const socket = last();
    client.stop();
    assert.equal(socket.closed, true);
    assert.equal(client.status, "closed");
    socket.drop(); // late close event from the old socket
    timers.advance(120_000);
    assert.equal(FakeSocket.instances.length, 1);
  });

  it("cancels a pending reconnect", () => {
    const client = makeClient();
    client.start();
    last().drop();
    client.stop();
    timers.advance(60_000);
    assert.equal(FakeSocket.instances.length, 1);
  });

  it("can be started again afterwards", () => {
    const client = makeClient();
    connectAndGoLive(client);
    client.stop();
    client.start();
    assert.equal(FakeSocket.instances.length, 2);
  });

  it("ignores messages from a socket that was replaced", () => {
    const client = makeClient();
    connectAndGoLive(client);
    const old = last();
    old.drop();
    timers.advance(1000);
    old.receive({ type: "product.checked", data: {} });
    assert.equal(events.length, 0);
  });
});
