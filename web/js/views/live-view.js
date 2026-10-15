// Live: the tuning board. Every handling characteristic flies a status plate
// (colour + OK / Watch / Fix / Collecting), its value against the target
// band, and the change to make in game-menu wording beside it. Rows keep
// fixed positions so the eye learns where each item lives. Timing, tyres
// and inputs sit to the side, secondary.

import { h, clear, setText, setAttr, replay, flag, gameText } from "../dom.js";
import { icon } from "../icons.js";
import { store, feedState } from "../store.js";
import * as U from "../units.js";
import { describeError } from "../api.js";
import { toast } from "../shell.js";
import { setupPanel } from "./setup.js";

const STATUS = {
  ok: { word: "OK", sr: "OK, inside target" },
  warn: { word: "Watch", sr: "Watch, drifting outside target" },
  bad: { word: "Fix", sr: "Fix, well outside target" },
  collecting: { word: "Collecting", sr: "Collecting samples" },
};

// ------------------------------------------------------------ target band

const NUM = "([+-]?\\d+(?:\\.\\d+)?)";

/** Target band from item.target ([lo, hi] or {low, high}) or parsed from target_text. */
export function parseTarget(item) {
  const t = item.target;
  if (Array.isArray(t) && t.length === 2) return { lo: t[0], hi: t[1] };
  if (t && typeof t === "object" && ("low" in t || "high" in t)) return { lo: t.low ?? null, hi: t.high ?? null };
  const text = String(item.target_text || "").replace(/−/g, "-").replace(/\s+/g, " ");
  let m = text.match(new RegExp(`${NUM}\\s*(?:…|\\.\\.\\.|to|–|—)\\s*${NUM}`));
  if (m) return { lo: Number(m[1]), hi: Number(m[2]) };
  m = text.match(new RegExp(`(?:≤|<=|<|under|max\\.?|at most)\\s*${NUM}`, "i"));
  if (m) return { lo: null, hi: Number(m[1]) };
  m = text.match(new RegExp(`(?:≥|>=|>|over|min\\.?|at least)\\s*${NUM}`, "i"));
  if (m) return { lo: Number(m[1]), hi: null };
  return null;
}

function gaugeGeometry(value, band) {
  if (!band || value === null || value === undefined || Number.isNaN(value)) return null;
  let { lo, hi } = band;
  let d0, d1;
  if (lo !== null && hi !== null) {
    const w = Math.max(hi - lo, 1e-6);
    d0 = lo - w * 1.25;
    d1 = hi + w * 1.25;
  } else if (hi !== null) {
    lo = Math.min(0, hi);
    d0 = lo;
    d1 = Math.max(hi * 3.2, 1e-6);
  } else {
    hi = null;
    d0 = Math.min(0, lo);
    d1 = Math.max(lo * 2, 1e-6);
  }
  d0 = Math.min(d0, value - Math.abs(d1 - d0) * 0.06);
  d1 = Math.max(d1, value + Math.abs(d1 - d0) * 0.06);
  const pos = (x) => ((x - d0) / (d1 - d0)) * 100;
  return {
    bandLeft: pos(lo),
    bandRight: hi === null ? 100 : pos(hi),
    value: pos(value),
    zero: d0 < 0 && d1 > 0 ? pos(0) : null,
  };
}

// ------------------------------------------------------------------- view

export function mount(main, ctx) {
  const { api } = ctx;
  const cleanup = [];

  // notice area (setup hint, offline, menus)
  const notice = h("div", { class: "live__notice" });

  // board head
  const windowEl = h("span", { class: "board__window num" });
  const resetBtn = h("button", { class: "btn board__reset", type: "button", title: "After a setup change" }, icon("reset"), h("span", null, "Reset board"));
  resetBtn.addEventListener("click", async () => {
    resetBtn.disabled = true;
    resetBtn.setAttribute("aria-busy", "true");
    try {
      const snap = await api.resetLiveAnalysis();
      store.set("liveAnalysis", snap);
      toast("Board reset");
    } catch (e) {
      toast(describeError(e), { kind: "error" });
    } finally {
      resetBtn.disabled = false;
      resetBtn.removeAttribute("aria-busy");
    }
  });
  const boardTitle = h("h1", { id: "board-title", class: "board__title" }, "Tuning board");
  const stateFlag = flag("none");
  const stateText = h("span", null, "");
  const stateEl = h("span", { class: "board__state signal", role: "status" }, stateFlag, stateText);
  const list = h("ol", { class: "board__list", "aria-labelledby": "board-title" });
  const baseName = h("b");
  const baseLink = h("a", { class: "board__baseline link-quiet", href: "#/baseline", hidden: true }, h("span", { class: "muted" }, "Baseline"), baseName, icon("arrowRight"));
  const board = h("section", { class: "board", "aria-labelledby": "board-title" },
    h("div", { class: "board__head" }, boardTitle, stateEl, windowEl, baseLink, resetBtn),
    list);

  const side = buildSide();
  const root = h("div", { class: "live" }, notice, board, side.el);
  main.append(root);

  // ---------------------------------------------------------------- board
  let rows = new Map();
  let idsKey = "";
  let lastFocus = null;

  function buildRow(item) {
    const plate = h("span", { class: "plate" });
    const srStatus = h("span", { class: "sr-only" });
    const title = h("span", { class: "item__title" });
    const meta = h("span", { class: "item__meta num" });
    const value = h("span", { class: "item__value num" });
    const band = h("i", { class: "gauge__band" });
    const zero = h("i", { class: "gauge__zero" });
    const marker = h("i", { class: "gauge__value" });
    const gauge = h("div", { class: "gauge", "aria-hidden": "true" }, band, zero, marker);
    const target = h("span", { class: "item__target num" });
    const rec = h("span", { class: "item__rec" });
    const recMeta = h("span", { class: "item__recmeta num" });
    const reasonText = h("span");
    const reason = h("p", { class: "item__reason num" }, reasonText);
    const srFocus = h("span", { class: "sr-only" });
    const el = h("li", { class: "item" },
      h("div", { class: "item__status" }, plate, srStatus, srFocus),
      h("div", { class: "item__name" }, title, h("span", { class: "item__sub" }, meta, target)),
      h("div", { class: "item__reading" }, value, gauge),
      h("div", { class: "item__change" }, rec, recMeta),
      reason);
    return { el, plate, srStatus, srFocus, title, meta, value, gauge, band, zero, marker, target, rec, recMeta, reason, reasonText, status: null, recText: null };
  }

  function patchRow(r, item, isFocus) {
    const st = STATUS[item.status] ? item.status : "collecting";
    if (r.status !== st) {
      r.plate.className = `plate plate--${st}`;
      setText(r.plate, STATUS[st].word);
      if (r.status !== null) replay(r.plate, "is-changed");
      r.el.dataset.status = st;
      r.status = st;
    }
    setText(r.srStatus, `: ${STATUS[st].sr}`);
    setText(r.title, item.title);
    setText(r.meta, `${item.group}${item.samples !== undefined ? ` · n ${item.samples}` : ""}`);
    r.meta.title = item.samples !== undefined ? `${item.samples} samples` : "";
    setText(r.value, item.value_text ?? (st === "collecting" ? "–" : String(item.value ?? "–")));
    r.el.classList.toggle("is-focus", isFocus);
    setText(r.srFocus, isFocus ? ". Change this first." : "");
    const rc = item.recommendation;
    r.reason.hidden = !isFocus || !rc?.reason;
    if (isFocus) setText(r.reasonText, rc?.reason ? U.minus(String(rc.reason).trim().replace(/\.+$/, "")) : "");

    const geo = gaugeGeometry(item.value, parseTarget(item));
    r.gauge.hidden = !geo;
    if (geo) {
      r.gauge.className = `gauge gauge--${st}`;
      r.band.style.left = `${geo.bandLeft}%`;
      r.band.style.width = `${Math.max(0.5, geo.bandRight - geo.bandLeft)}%`;
      r.zero.hidden = geo.zero === null;
      if (geo.zero !== null) r.zero.style.left = `${geo.zero}%`;
      r.marker.style.left = `${Math.min(100, Math.max(0, geo.value))}%`;
    }
    setText(r.target, item.target_text ? ` · ${U.minus(item.target_text)}` : "");
    r.target.title = item.target_text ? "Target" : "";

    const recText = item.recommendation?.text || null;
    if (recText !== r.recText) {
      clear(r.rec);
      if (recText) r.rec.append(gameText(recText));
      r.recText = recText;
    }
    r.rec.classList.toggle("is-empty", !recText);
    if (!recText) {
      setText(r.rec, st === "ok" ? "No change" : "–");
      r.recText = null;
      setText(r.recMeta, "");
    } else {
      const c = item.recommendation.confidence;
      setText(r.recMeta, c !== undefined && c !== null ? `${Math.round(c * 100)}%` : "");
      r.recMeta.title = "Confidence";
    }
  }

  function skeletonBoard() {
    clear(list);
    for (let i = 0; i < 8; i++) list.append(h("li", { class: "item item--skeleton", "aria-hidden": "true" }, h("span", { class: "skeleton" })));
    idsKey = "";
    rows = new Map();
  }

  function renderBoard() {
    const la = store.get("liveAnalysis");
    if (!la || !Array.isArray(la.items)) {
      if (!list.firstChild) skeletonBoard();
      setText(windowEl, "");
      renderState(null);
      return;
    }
    const key = la.items.map((i) => i.id).join("|");
    if (key !== idsKey) {
      clear(list);
      rows = new Map();
      for (const item of la.items) rows.set(item.id, buildRow(item));
      idsKey = key;
      lastFocus = undefined;
    }
    const focusId = la.focus && rows.has(la.focus) ? la.focus : null;
    for (const item of la.items) patchRow(rows.get(item.id), item, item.id === focusId);
    // The focus item leads the board: first, full width, larger. Others keep server order.
    if (focusId !== lastFocus) {
      const ordered = focusId ? [focusId, ...la.items.map((i) => i.id).filter((id) => id !== focusId)] : la.items.map((i) => i.id);
      ordered.forEach((id) => list.append(rows.get(id).el));
      const rest = la.items.length - (focusId ? 1 : 0);
      list.style.setProperty("--rows", String(Math.max(1, Math.ceil(rest / 2))));
      list.classList.toggle("has-focus", !!focusId);
      if (focusId && lastFocus !== undefined) replay(rows.get(focusId).el, "is-arrived");
      lastFocus = focusId;
    }
    const w = la.window || {};
    const parts = [];
    if (w.corners !== undefined) parts.push(`Last ${w.corners} ${w.corners === 1 ? "corner" : "corners"}${w.laps !== undefined ? ` · ${w.laps} ${w.laps === 1 ? "lap" : "laps"}` : ""}`);
    if (la.corners_seen !== undefined) parts.push(`${la.corners_seen} since reset`);
    setText(windowEl, parts.join(" · ") || "");
    if (la.items.length === 0) {
      clear(list);
      list.append(h("li", { class: "empty" }, "No items"));
      idsKey = "";
    }
    renderState(la, focusId);
  }

  function renderState(la, focusId) {
    if (!la) {
      stateFlag.className = "flag flag--none";
      setText(stateText, "Connecting");
      return;
    }
    if (focusId) {
      const item = la.items.find((i) => i.id === focusId);
      stateFlag.className = `flag flag--${item.status === "bad" ? "red" : "yellow"}`;
      setText(stateText, `Next: ${item.title}`);
      return;
    }
    const collecting = la.items.length && la.items.every((i) => i.status === "collecting");
    stateFlag.className = `flag flag--${collecting ? "none" : "green"}`;
    setText(stateText, collecting ? "Collecting" : "All OK");
  }

  // ----------------------------------------------------------- feed state
  let lastFeedKey = null;
  function renderFeed() {
    const st = store.get("status");
    const feed = feedState(st, store.get("connection"));
    const key = `${feed}|${st?.receiver?.udp_port}|${st?.receiver?.public_host}|${st?.receiver?.listening}`;
    root.dataset.feed = feed;
    if (key === lastFeedKey) return;
    lastFeedKey = key;
    clear(notice);
    if (feed === "waiting" || feed === "not-listening") {
      notice.append(setupPanel(st, feed));
      setText(boardTitle, "Tuning board, paused");
    } else if (feed === "offline") {
      // The strip already flies the red flag and Retry; the board just says what it shows.
      setText(boardTitle, "Tuning board, last ratings");
    } else if (feed === "menu") {
      setText(boardTitle, "Tuning board, paused");
    } else {
      setText(boardTitle, "Tuning board");
    }
  }

  // --------------------------------------------------------------- wiring
  renderFeed();
  renderBoard();
  if (!store.get("liveAnalysis")) {
    api.liveAnalysis().then((a) => { if (!store.get("liveAnalysis")) store.set("liveAnalysis", a); }).catch(() => {});
  }
  cleanup.push(store.on("liveAnalysis", renderBoard));
  cleanup.push(store.on("status", () => { renderFeed(); side.renderStatus(store.get("status")); }));
  cleanup.push(store.on("connection", renderFeed));
  cleanup.push(store.on("telemetry", (f) => side.pushFrame(f)));
  cleanup.push(store.on("settings", () => { side.renderUnits(); renderBoard(); }));
  side.renderStatus(store.get("status"));
  if (store.get("telemetry")) side.pushFrame(store.get("telemetry"));

  // compact baseline entry: the category matched for the car on track
  let baseFor;
  let alive = true;
  function renderBaseline() {
    const car = store.get("status")?.car;
    const key = car ? `${car.ordinal}|${car.class}|${car.drivetrain}` : "";
    if (key === baseFor) return;
    baseFor = key;
    if (!car) { baseLink.hidden = true; return; }
    api.baseline().then((res) => {
      if (!alive || baseFor !== key) return;
      const cat = res?.baseline?.category;
      baseLink.hidden = !cat;
      if (cat) setText(baseName, cat.name);
    }).catch(() => { if (alive) baseLink.hidden = true; });
  }
  renderBaseline();
  cleanup.push(store.on("status", renderBaseline));
  cleanup.push(() => { alive = false; });

  return () => {
    cleanup.forEach((fn) => fn());
    side.destroy();
  };
}

// --------------------------------------------------------------- sidebar

function buildSide() {
  // timing
  const lapNo = h("span", { class: "num" }, "–");
  const current = h("p", { class: "timing__current num" }, U.fmtLapTime(null));
  const last = h("dd", { class: "num" }, U.fmtLapTime(null));
  const best = h("dd", { class: "num" }, U.fmtLapTime(null));
  const delta = h("dd", { class: "num timing__delta" }, "–");
  const deltaWord = h("span", { class: "sr-only" });
  const timing = h("section", { class: "side__block timing", "aria-label": "Lap times" },
    h("h2", { class: "side__title" }, "Lap ", lapNo),
    current,
    h("dl", { class: "timing__rows" },
      h("div", null, h("dt", null, "Last"), last),
      h("div", null, h("dt", null, "Best"), best),
      h("div", null, h("dt", null, "Last vs best"), delta, deltaWord)));

  // tyres
  const tyreEls = {};
  const mkTyre = (w, label) => {
    const fill = h("i", { class: "tyre__fill" });
    const win = h("i", { class: "tyre__window" });
    const temp = h("span", { class: "tyre__temp num" }, "–");
    const state = h("span", { class: "tyre__state" }, "");
    const slip = h("span", { class: "tyre__slip", hidden: true }, flag("slippery"), h("span", null, ""));
    const el = h("div", { class: `tyre tyre--${w}` },
      h("div", { class: "tyre__bar", "aria-hidden": "true" }, win, fill),
      h("div", { class: "tyre__read" }, h("span", { class: "tyre__label" }, label), temp, state, slip));
    tyreEls[w] = { el, fill, win, temp, state, slip, slipText: slip.lastChild, hold: 0, holdKind: "" };
    return el;
  };
  const nowWord = h("span", { class: "now__word" }, "–");
  const nowEl = h("div", { class: "carplan__now" }, h("span", { class: "now__label" }, "Now"), nowWord);
  const windowNote = h("span", { class: "side__note" });
  const tyres = h("section", { class: "side__block tyres", "aria-label": "Tyre temperatures" },
    h("h2", { class: "side__title" }, "Tyres ", windowNote),
    h("div", { class: "carplan" },
      mkTyre("fl", "FL"), mkTyre("fr", "FR"), nowEl, mkTyre("rl", "RL"), mkTyre("rr", "RR")));

  // inputs
  const lanes = [
    { key: "throttle", label: "Throttle", color: "--series-throttle", min: 0, max: 1, fill: true },
    { key: "brake", label: "Brake", color: "--series-brake", min: 0, max: 1, fill: true },
    { key: "steer", label: "Steer", color: "--series-steer", min: -1, max: 1, fill: false },
  ].map((lane) => {
    const canvas = h("canvas", { class: "lane__canvas", "aria-hidden": "true" });
    const val = h("span", { class: "lane__value num" }, "–");
    const el = h("div", { class: `lane lane--${lane.key}` }, h("span", { class: "lane__label" }, lane.label), val, canvas);
    return { ...lane, canvas, val, el };
  });
  const inputs = h("section", { class: "side__block inputs", "aria-label": "Inputs, last 10 seconds" },
    h("h2", { class: "side__title" }, "Inputs ", h("span", { class: "side__note" }, "last 10 s")),
    h("div", { class: "lanes" }, lanes.map((l) => l.el)));

  const el = h("aside", { class: "side", "aria-label": "Timing, tyres and inputs" }, timing, tyres, inputs);

  // ring buffer
  const N = 200;
  const buf = { throttle: new Float32Array(N), brake: new Float32Array(N), steer: new Float32Array(N) };
  let head = 0;
  let count = 0;
  let raf = 0;
  let drivetrain = "RWD";

  const colors = {};
  function readColors() {
    const cs = getComputedStyle(document.documentElement);
    for (const l of lanes) colors[l.key] = cs.getPropertyValue(l.color).trim() || "#fff";
    colors.rule = cs.getPropertyValue("--rule").trim();
  }
  readColors();

  function sizeCanvases() {
    const dpr = window.devicePixelRatio || 1;
    for (const l of lanes) {
      const w = l.canvas.clientWidth;
      const hgt = l.canvas.clientHeight;
      if (!w || !hgt) continue;
      l.canvas.width = Math.round(w * dpr);
      l.canvas.height = Math.round(hgt * dpr);
    }
    draw();
  }
  const ro = new ResizeObserver(sizeCanvases);
  lanes.forEach((l) => ro.observe(l.canvas));

  function draw() {
    raf = 0;
    for (const l of lanes) {
      const c = l.canvas;
      const ctx = c.getContext("2d");
      const W = c.width, H = c.height;
      ctx.clearRect(0, 0, W, H);
      ctx.strokeStyle = colors.rule;
      ctx.lineWidth = 1;
      if (l.min < 0) {
        ctx.beginPath();
        ctx.moveTo(0, H / 2 + 0.5);
        ctx.lineTo(W, H / 2 + 0.5);
        ctx.stroke();
      }
      if (!count) continue;
      const data = buf[l.key];
      const y = (v) => H - ((v - l.min) / (l.max - l.min)) * (H - 4) - 2;
      ctx.beginPath();
      for (let i = 0; i < count; i++) {
        const idx = (head - count + i + N) % N;
        const x = (W * (N - count + i)) / (N - 1);
        const yy = y(data[idx]);
        if (i === 0) ctx.moveTo(x, yy);
        else ctx.lineTo(x, yy);
      }
      ctx.strokeStyle = colors[l.key];
      ctx.lineWidth = Math.max(2, (window.devicePixelRatio || 1) * 1.75);
      ctx.lineJoin = "round";
      ctx.stroke();
      if (l.fill) {
        ctx.lineTo(W, H);
        ctx.lineTo((W * (N - count)) / (N - 1), H);
        ctx.closePath();
        ctx.globalAlpha = 0.22;
        ctx.fillStyle = colors[l.key];
        ctx.fill();
        ctx.globalAlpha = 1;
      }
    }
  }

  function renderUnits() {
    setText(windowNote, `window ${Math.round(U.tempValue(U.TIRE_WINDOW_C[0]))}–${Math.round(U.tempValue(U.TIRE_WINDOW_C[1]))} ${U.tempUnit()}`);
    windowNote.title = "Rule of thumb";
  }
  renderUnits();

  let lastBest = null;
  function pushFrame(f) {
    if (!f) return;
    // timing
    setText(lapNo, f.lap_number !== undefined ? String(f.lap_number + 1) : "–");
    setText(current, U.fmtLapTime(f.current_lap));
    setText(last, U.fmtLapTime(f.last_lap));
    setText(best, U.fmtLapTime(f.best_lap));
    if (f.last_lap > 0 && f.best_lap > 0) {
      const d = f.last_lap - f.best_lap;
      setText(delta, U.fmtDelta(d));
      delta.dataset.sign = d > 0.0005 ? "slower" : d < -0.0005 ? "faster" : "even";
      setText(deltaWord, d > 0.0005 ? " slower" : " best lap");
    } else {
      setText(delta, "–");
      delete delta.dataset.sign;
    }
    if (lastBest !== null && f.best_lap && f.best_lap < lastBest - 0.0005) replay(best, "is-new-best");
    lastBest = f.best_lap || lastBest;

    // tyres
    const now = performance.now();
    const driven = drivetrain === "FWD" ? ["fl", "fr"] : drivetrain === "AWD" ? ["fl", "fr", "rl", "rr"] : ["rl", "rr"];
    for (const w of ["fl", "fr", "rl", "rr"]) {
      const t = tyreEls[w];
      const c = f.tire_temp?.[w];
      setText(t.temp, U.fmtTemp(c));
      const state = U.tireState(c);
      t.el.dataset.state = state;
      setText(t.state, state === "cold" ? "Cold" : state === "hot" ? "Hot" : state === "ok" ? "In window" : "");
      const [s0, s1] = U.TIRE_SCALE_C;
      const p = (x) => Math.min(100, Math.max(0, ((x - s0) / (s1 - s0)) * 100));
      t.fill.style.height = `${p(c ?? s0)}%`;
      t.win.style.bottom = `${p(U.TIRE_WINDOW_C[0])}%`;
      t.win.style.height = `${p(U.TIRE_WINDOW_C[1]) - p(U.TIRE_WINDOW_C[0])}%`;
      const ratio = f.slip_ratio?.[w] ?? 0;
      let kind = "";
      if (ratio < -1 && f.brake > 0.1) kind = "Lock";
      else if (ratio > 1 && driven.includes(w) && f.throttle > 0.2) kind = "Spin";
      if (kind) {
        t.hold = now + 700;
        t.holdKind = kind;
      }
      const show = now < t.hold;
      t.slip.hidden = !show;
      if (show) setText(t.slipText, t.holdKind);
    }
    // instantaneous balance
    const sa = f.slip_angle || {};
    const front = (Math.abs(sa.fl ?? 0) + Math.abs(sa.fr ?? 0)) / 2;
    const rear = (Math.abs(sa.rl ?? 0) + Math.abs(sa.rr ?? 0)) / 2;
    const bal = front - rear;
    let word = "Straight";
    if (Math.abs(f.lat_g ?? 0) > 0.35 && f.speed > 8) word = bal > 0.08 ? "Understeer" : bal < -0.08 ? "Oversteer" : "Neutral";
    setText(nowWord, word);
    nowEl.dataset.state = word.toLowerCase();

    // inputs
    buf.throttle[head] = f.throttle ?? 0;
    buf.brake[head] = f.brake ?? 0;
    buf.steer[head] = f.steer ?? 0;
    head = (head + 1) % N;
    count = Math.min(N, count + 1);
    setText(lanes[0].val, U.pct(f.throttle));
    setText(lanes[1].val, U.pct(f.brake));
    setText(lanes[2].val, U.signed((f.steer ?? 0) * 100, 0, "%"));
    if (!raf) raf = requestAnimationFrame(draw);
  }

  function renderStatus(st) {
    if (st?.car?.drivetrain) drivetrain = st.car.drivetrain;
  }

  return {
    el,
    pushFrame,
    renderStatus,
    renderUnits,
    destroy() {
      ro.disconnect();
      cancelAnimationFrame(raf);
    },
  };
}
