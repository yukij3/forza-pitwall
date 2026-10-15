// Entry point: picks the real backend or the in-browser mock (?mock=1),
// wires the live socket into the store, mounts the shell and routes views.

import { createApi, describeError } from "./api.js";
import { LiveClient } from "./live.js";
import { store } from "./store.js";
import { setUnits } from "./units.js";
import { onRoute, sectionOf } from "./router.js";
import { mountShell, toast } from "./shell.js";
import { h, clear } from "./dom.js";

const params = new URLSearchParams(location.search);
const isMock = params.get("mock") === "1";

let mock = null;
if (isMock) {
  const { createMockBackend } = await import("./mock.js");
  mock = createMockBackend();
  document.title = "Pitwall (demo)";
}

const api = createApi(mock ? mock.fetch : undefined);
const live = new LiveClient(mock ? { WebSocketImpl: mock.WebSocket } : {});
store.set("mock", isMock);

const ctx = { api, live, mock, toast };
const shell = mountShell(document.getElementById("app"), ctx);

// ------------------------------------------------------------- live feed
live.addEventListener("state", (e) => store.set("connection", e.detail));
live.addEventListener("status", (e) => {
  const { type, ...status } = e.detail;
  store.set("status", status);
});
live.addEventListener("telemetry", (e) => store.set("telemetry", e.detail));
live.addEventListener("live_analysis", (e) => {
  const { type, ...la } = e.detail;
  store.set("liveAnalysis", la);
});
live.addEventListener("lap_completed", (e) => {
  const { lap, session_id } = e.detail;
  store.set("lapCompleted", e.detail);
  if (!lap) return;
  const time = lap.lap_time ? ` · ${formatLap(lap.lap_time)}` : "";
  const note = lap.valid ? "" : ` · ${lap.invalid_reason || "not valid"}`;
  toast(h("span", null, `Lap ${lap.number}${time}${note} `, h("a", { href: `#/laps/${lap.id}` }, "Open")), { timeout: 6000 });
  void session_id;
});
live.addEventListener("analysis_ready", (e) => store.set("analysisReady", e.detail));
live.start();

function formatLap(s) {
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(3).padStart(6, "0")}`;
}

// ----------------------------------------------------------- first loads
api.settings()
  .then((s) => {
    setUnits(s.units);
    store.set("settings", s);
  })
  .catch((e) => {
    if (e.code !== "network") toast(`Settings not loaded: ${describeError(e)}`, { kind: "error" });
  });
api.status().then((s) => { if (!store.get("status")) store.set("status", s); }).catch(() => {});
store.on("settings", (s) => s && setUnits(s.units));

// ---------------------------------------------------------------- router
const VIEWS = {
  live: () => import("./views/live-view.js"),
  sessions: () => import("./views/sessions.js"),
  session: () => import("./views/session.js"),
  lap: () => import("./views/lap.js"),
  baseline: () => import("./views/baseline.js"),
  settings: () => import("./views/settings.js"),
};

let unmount = null;
let token = 0;
onRoute(async (route) => {
  const my = ++token;
  if (unmount) {
    try { unmount(); } catch { /* view already gone */ }
    unmount = null;
  }
  const main = shell.main;
  clear(main);
  shell.setSection(sectionOf(route));
  if (route.name === "notfound") {
    main.append(h("div", { class: "empty" }, h("h2", null, "Not found"), h("a", { href: "#/live" }, "Live")));
    return;
  }
  try {
    const mod = await VIEWS[route.name]();
    if (my !== token) return;
    unmount = mod.mount(main, ctx, route) || null;
    const heading = main.querySelector("h1");
    document.title = `${heading ? `${heading.textContent} · ` : ""}Pitwall${isMock ? " (demo)" : ""}`;
  } catch (e) {
    console.error(e);
    if (my !== token) return;
    main.append(h("div", { class: "notice notice--error" }, `Screen failed: ${describeError(e)}`));
  }
});
