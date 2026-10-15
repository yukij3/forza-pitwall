// Shared app state with keyed subscriptions.

const state = {
  settings: null,
  status: null,
  connection: { state: "idle", attempt: 0, retryAt: null },
  telemetry: null,
  liveAnalysis: null,
  schema: null,
  mock: false,
};
const listeners = new Map();

export const store = {
  get(key) {
    return state[key];
  },
  set(key, value) {
    state[key] = value;
    const fns = listeners.get(key);
    if (fns) for (const fn of [...fns]) fn(value);
  },
  on(key, fn) {
    if (!listeners.has(key)) listeners.set(key, new Set());
    listeners.get(key).add(fn);
    return () => listeners.get(key)?.delete(fn);
  },
};

/** One answer to "is data flowing?", derived from the socket and the receiver status. */
export function feedState(status = state.status, connection = state.connection) {
  if (connection.state !== "open") {
    // First connect: not a failure yet, even if REST status already arrived.
    return connection.state === "connecting" ? "connecting" : "offline";
  }
  if (!status) return "connecting";
  const r = status.receiver || {};
  if (r.listening === false) return "not-listening";
  const age = r.last_packet_age_s;
  if (!(r.packets_per_sec > 0) || age === null || age === undefined || age > 3) return "waiting";
  if (!r.race_on) return "menu";
  return "live";
}

export const FEED = {
  live: { flag: "green", word: "Receiving" },
  menu: { flag: "yellow", word: "In menus or paused" },
  waiting: { flag: "yellow", word: "Waiting for the game" },
  "not-listening": { flag: "red", word: "Receiver not listening" },
  connecting: { flag: "none", word: "Connecting" },
  offline: { flag: "red", word: "Server unreachable" },
};
