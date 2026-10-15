// Persistent shell: orange rail, status strip (connection, car, track,
// recording), toasts. Visible on every screen so recording state and the
// data feed are never more than a glance away.

import { h, clear, setText, setAttr, flag } from "./dom.js";
import { icon, brandMark } from "./icons.js";
import { store, feedState, FEED } from "./store.js";
import { carLabel, trackLabel, fmtDuration } from "./units.js";
import { describeError } from "./api.js";

const NAV = [
  ["live", "Live", "#/live"],
  ["sessions", "Sessions", "#/sessions"],
  ["baseline", "Baseline", "#/baseline"],
  ["settings", "Settings", "#/settings"],
];

let toastRoot;

export function toast(message, { kind = "info", timeout = 5000 } = {}) {
  if (!toastRoot) return;
  const el = h("div", { class: ["toast", kind === "error" && "toast--error"], role: kind === "error" ? "alert" : "status" }, message);
  toastRoot.append(el);
  setTimeout(() => el.remove(), timeout);
}

export function mountShell(root, ctx) {
  const { api, live, mock } = ctx;

  // ---------------------------------------------------------------- rail
  const links = new Map();
  const rail = h("nav", { class: "rail", "aria-label": "Main" },
    h("a", { class: "rail__brand", href: "#/live" }, brandMark(), h("span", null, "Pitwall")),
    h("ul", { class: "rail__nav" }, NAV.map(([key, label, href]) => {
      const a = h("a", { class: "rail__link", href }, icon(key), h("span", null, label));
      links.set(key, a);
      return h("li", null, a);
    })),
    h("p", { class: "rail__foot" }, mock ? "Demo data" : "")
  );

  // --------------------------------------------------------------- strip
  const connFlag = flag("none");
  const connWord = h("span", null, "Connecting");
  const connDetail = h("span", { class: "detail num" });
  const retryBtn = h("button", { class: "btn btn--sm btn--quiet", type: "button", hidden: true, onclick: () => live.retryNow() }, "Retry now");
  const conn = h("div", { class: "strip__group strip__conn", role: "status", "aria-live": "polite" }, connFlag, connWord, connDetail, retryBtn);

  const carEl = h("b", { class: "strip__car" });
  const carMeta = h("span", { class: "num" });
  const trackEl = h("b");
  const context = h("div", { class: "strip__context" },
    h("span", { class: "strip__carline" }, carEl, carMeta),
    h("span", null, trackEl)
  );

  let demo = null;
  if (mock) {
    const select = h("select", { "aria-label": "Demo scenario", onchange: (e) => mock.setScenario(e.target.value) },
      mock.scenarios.map(([v, label]) => h("option", { value: v, selected: v === mock.scenario }, label)));
    demo = h("div", { class: "demo-tag" }, h("span", null, "Demo", h("span", { class: "demo-tag__long" }, ", simulated data")), select);
  }

  const recLamp = h("span", { class: "rec-lamp", "aria-hidden": "true" });
  const recTime = h("span", { class: "num" }, "0:00");
  const recLaps = h("span", { class: "laps num" });
  const recReadout = h("div", { class: "rec-readout", hidden: true }, recLamp, h("span", null, "REC ", recTime), recLaps);
  const startBtn = h("button", { class: "btn btn--primary btn--rec", type: "button" }, h("span", { class: "dot", "aria-hidden": "true" }), "Start recording");
  const stopBtn = h("button", { class: "btn btn--stop", type: "button", hidden: true }, h("span", { class: "sq", "aria-hidden": "true" }), "Stop recording");
  const strip = h("header", { class: "strip", "data-recording": "false" },
    conn, context,
    h("div", { class: "strip__end" }, demo, recReadout, startBtn, stopBtn)
  );

  async function recordingAction(btn, fn, busyLabel) {
    const label = btn.lastChild.textContent;
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    btn.lastChild.textContent = busyLabel;
    try {
      const session = await fn();
      const st = await api.status().catch(() => null);
      if (st) store.set("status", st);
      return session;
    } catch (e) {
      toast(describeError(e), { kind: "error" });
    } finally {
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
      btn.lastChild.textContent = label;
    }
  }
  startBtn.addEventListener("click", () => recordingAction(startBtn, () => api.startRecording(), "Starting…"));
  stopBtn.addEventListener("click", async () => {
    const s = await recordingAction(stopBtn, () => api.stopRecording(), "Stopping…");
    if (s) toast(h("span", null, `Session ${s.id} saved `, h("a", { href: `#/sessions/${s.id}` }, "Open")));
  });

  const main = h("main", { id: "main", class: "main", tabindex: "-1" });
  toastRoot = h("div", { class: "toasts", "aria-live": "polite" });
  clear(root);
  root.append(h("a", { class: "skip-link", href: "#main", onclick: (e) => { e.preventDefault(); main.focus(); } }, "Skip to content"),
    h("div", { class: "app" }, rail, strip, main), toastRoot);

  // ------------------------------------------------------------- updates
  let lastFeed = null;
  function renderConn() {
    const st = store.get("status");
    const c = store.get("connection");
    const feed = feedState(st, c);
    const meta = FEED[feed];
    if (feed !== lastFeed) {
      connFlag.className = `flag flag--${meta.flag} is-new`;
      lastFeed = feed;
    }
    setText(connWord, meta.word);
    retryBtn.hidden = feed !== "offline";
    let detail = "";
    if (feed === "offline" && c.retryAt) {
      const secs = Math.max(0, Math.ceil((c.retryAt - Date.now()) / 1000));
      detail = secs > 0 ? `retrying in ${secs} s` : "retrying…";
    } else if (feed === "live" || feed === "menu") {
      detail = `${Math.round(st.receiver.packets_per_sec)} pkt/s`;
    } else if (feed === "waiting") {
      const age = st?.receiver?.last_packet_age_s;
      detail = age ? `last packet ${Math.round(age)} s ago` : `UDP ${st?.receiver?.udp_port ?? ""}`;
    }
    setText(connDetail, detail);
  }

  function renderStatus() {
    const st = store.get("status");
    renderConn();
    const car = st?.car;
    const spec = car ? `${carLabel(car)} · ${car.drivetrain}` : "";
    setText(carEl, car ? car.name || spec : "No car");
    setAttr(carEl, "title", car?.name ? `${car.name}${car.division ? ` · ${car.division}` : ""}` : null);
    setText(carMeta, car?.name ? spec : "");
    setText(trackEl, st?.track_ordinal != null ? trackLabel(st.track_ordinal) : "");
    const rec = st?.recording;
    const recording = !!rec?.active;
    strip.dataset.recording = String(recording);
    recReadout.hidden = !recording;
    stopBtn.hidden = !recording;
    startBtn.hidden = recording;
    startBtn.disabled = !st;
    if (recording) {
      setText(recLaps, `${rec.laps} ${rec.laps === 1 ? "lap" : "laps"} · session ${rec.session_id}`);
      renderElapsed();
    }
  }
  function renderElapsed() {
    const rec = store.get("status")?.recording;
    if (!rec?.active || !rec.started_at) return;
    const secs = (Date.now() - new Date(rec.started_at).getTime()) / 1000;
    setText(recTime, fmtDuration(secs));
  }

  store.on("status", renderStatus);
  store.on("connection", renderConn);
  const timer = setInterval(() => {
    renderElapsed();
    if (store.get("connection").state !== "open") renderConn();
  }, 1000);
  renderStatus();

  function setSection(section) {
    for (const [key, a] of links) setAttr(a, "aria-current", key === section ? "page" : null);
  }

  return { main, setSection, destroy: () => clearInterval(timer) };
}
