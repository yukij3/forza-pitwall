// /ws/live client: reconnects with capped exponential backoff and jitter,
// exposes a connection state the UI shows at all times, and re-emits each
// server message type ("status", "telemetry", "lap_completed",
// "analysis_ready", "live_analysis") as a DOM event.

const BACKOFF_S = [0.5, 1, 2, 4, 8, 15];
const WATCHDOG_MS = 6000; // server sends status at least once a second

export function liveUrl() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws/live`;
}

export class LiveClient extends EventTarget {
  constructor({ url = liveUrl(), WebSocketImpl } = {}) {
    super();
    this.url = url;
    this.WS = WebSocketImpl || window.WebSocket;
    this.ws = null;
    this.state = "idle"; // idle | connecting | open | reconnecting
    this.attempt = 0;
    this.retryAt = null;
    this.lastMessageAt = 0;
    this.messagesPerSec = 0;
    this._count = 0;
    this._timer = null;
    this._watchdog = null;
    this._rate = null;
    this._stopped = true;
    this._onVisible = () => {
      if (document.visibilityState === "visible" && this.state === "reconnecting") this.retryNow();
    };
    this._onOnline = () => {
      if (this.state === "reconnecting") this.retryNow();
    };
  }

  start() {
    if (!this._stopped) return;
    this._stopped = false;
    document.addEventListener("visibilitychange", this._onVisible);
    window.addEventListener("online", this._onOnline);
    this._rate = setInterval(() => {
      this.messagesPerSec = this._count;
      this._count = 0;
    }, 1000);
    this._connect();
  }

  stop() {
    this._stopped = true;
    clearTimeout(this._timer);
    clearInterval(this._watchdog);
    clearInterval(this._rate);
    document.removeEventListener("visibilitychange", this._onVisible);
    window.removeEventListener("online", this._onOnline);
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this._setState("idle");
  }

  retryNow() {
    if (this._stopped) return;
    clearTimeout(this._timer);
    this._connect();
  }

  _setState(state) {
    this.state = state;
    this.dispatchEvent(new CustomEvent("state", { detail: { state, attempt: this.attempt, retryAt: this.retryAt } }));
  }

  _connect() {
    this.retryAt = null;
    this._setState(this.attempt === 0 ? "connecting" : "reconnecting");
    let ws;
    try {
      ws = new this.WS(this.url);
    } catch {
      this._scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.attempt = 0;
      this.lastMessageAt = performance.now();
      this._setState("open");
      clearInterval(this._watchdog);
      this._watchdog = setInterval(() => {
        if (performance.now() - this.lastMessageAt > WATCHDOG_MS) {
          // Half-open socket: drop it and reconnect.
          ws.onclose = null;
          try { ws.close(); } catch { /* already closed */ }
          this._scheduleReconnect();
        }
      }, 1000);
    };
    ws.onmessage = (ev) => {
      this.lastMessageAt = performance.now();
      this._count += 1;
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg && typeof msg.type === "string") {
        this.dispatchEvent(new CustomEvent(msg.type, { detail: msg }));
      }
    };
    ws.onerror = () => { /* onclose follows */ };
    ws.onclose = () => {
      if (this.ws === ws) this.ws = null;
      clearInterval(this._watchdog);
      if (!this._stopped) this._scheduleReconnect();
    };
  }

  _scheduleReconnect() {
    clearInterval(this._watchdog);
    const base = BACKOFF_S[Math.min(this.attempt, BACKOFF_S.length - 1)];
    const delay = base * (0.8 + Math.random() * 0.4) * 1000;
    this.attempt += 1;
    this.retryAt = Date.now() + delay;
    this.state = "reconnecting";
    this.dispatchEvent(new CustomEvent("state", { detail: { state: "reconnecting", attempt: this.attempt, retryAt: this.retryAt } }));
    clearTimeout(this._timer);
    this._timer = setTimeout(() => this._connect(), delay);
  }
}
