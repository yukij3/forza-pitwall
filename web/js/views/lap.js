// Lap detail: metrics, charts against distance with an optional second lap
// overlaid, the track map from positions, and the lap's findings.

import { h, clear, flag, signal } from "../dom.js";
import { icon } from "../icons.js";
import * as U from "../units.js";
import { describeError } from "../api.js";
import { createLapCharts, createTrackMap } from "../charts.js";
import { renderLapFindings } from "./analysis.js";

const KIND = { out: "Out lap", flying: "Flying lap", in: "In lap", partial: "Partial lap" };

export function mount(main, ctx, route) {
  const { api } = ctx;
  const id = route.params.id;
  const vsId = route.query.vs || null;
  let alive = true;
  let charts = null;

  const crumbs = h("nav", { class: "crumbs", "aria-label": "Breadcrumb" }, h("a", { href: "#/sessions" }, "Sessions"));
  const head = h("div", { class: "lap-head" }, h("h1", null, `Lap`));
  const metricsEl = h("div", { class: "metrics" }, h("span", { class: "skeleton", style: { height: "3rem" } }));
  const chartsEl = h("div", { class: "lap__charts" }, h("span", { class: "skeleton", style: { height: "100%" } }));
  const mapEl = h("div", { class: "trackmap" }, h("span", { class: "skeleton", style: { height: "14rem" } }));
  const findingsEl = h("div", { class: "lap__findings" });
  const side = h("div", { class: "lap__side scroll-panel" }, h("h2", { class: "block-title" }, "Track map"), mapEl, findingsEl);
  main.append(h("div", { class: "view lap-view" }, crumbs, head, metricsEl, h("div", { class: "lap-grid" }, chartsEl, side)));

  async function load() {
    try {
      const lap = await api.lap(id);
      const [session, trace, analysis, vsLap, vsTrace] = await Promise.all([
        api.session(lap.session_id).catch(() => null),
        api.lapTrace(id, 20),
        api.lapAnalysis(id).catch(() => null),
        vsId ? api.lap(vsId).catch(() => null) : null,
        vsId ? api.lapTrace(vsId, 20).catch(() => null) : null,
      ]);
      if (!alive) return;
      render({ lap, session, trace, analysis, vsLap, vsTrace });
    } catch (e) {
      if (!alive) return;
      clear(main).append(h("div", { class: "notice notice--error" },
        e.status === 404 ? `Lap ${id} not found` : `Not loaded: ${describeError(e)}`));
    }
  }

  function render({ lap, session, trace, analysis, vsLap, vsTrace }) {
    const laps = session?.laps || [];
    const idx = laps.findIndex((l) => String(l.id) === String(lap.id));
    const prev = idx > 0 ? laps[idx - 1] : null;
    const next = idx >= 0 && idx < laps.length - 1 ? laps[idx + 1] : null;
    const valid = laps.filter((l) => l.valid && l.kind === "flying" && l.lap_time);
    const best = valid.length ? valid.reduce((a, b) => (b.lap_time < a.lap_time ? b : a)) : null;
    const isBest = best && best.id === lap.id;

    clear(crumbs).append(
      h("a", { href: "#/sessions" }, "Sessions"), h("span", { "aria-hidden": "true" }, "/"),
      h("a", { href: `#/sessions/${lap.session_id}` }, `Session ${lap.session_id}`), h("span", { "aria-hidden": "true" }, "/"),
      h("span", null, `Lap ${lap.number}`));

    const vsSelect = h("select", { class: "select", id: "vs-lap" },
      h("option", { value: "" }, "Nothing"),
      laps.filter((l) => l.id !== lap.id && l.lap_time).map((l) =>
        h("option", { value: l.id, selected: String(l.id) === String(vsId) },
          `Lap ${l.number} · ${U.fmtLapTime(l.lap_time)}${best && l.id === best.id ? " · best" : ""}${l.valid ? "" : " · not valid"}`)));
    vsSelect.addEventListener("change", () => {
      location.hash = vsSelect.value ? `#/laps/${lap.id}?vs=${vsSelect.value}` : `#/laps/${lap.id}`;
    });
    const nav = (l, dir) => l
      ? h("a", { class: "btn btn--sm", href: `#/laps/${l.id}${vsId ? `?vs=${vsId}` : ""}`, "aria-label": `${dir === "prev" ? "Previous" : "Next"}: lap ${l.number}` }, icon(dir === "prev" ? "chevronLeft" : "chevronRight"), `Lap ${l.number}`)
      : h("span", { class: "btn btn--sm", "aria-disabled": "true" }, icon(dir === "prev" ? "chevronLeft" : "chevronRight"), dir === "prev" ? "First lap" : "Last lap");
    clear(head).append(
      h("div", { class: "lap-title" },
        h("h1", null, `Lap ${lap.number}`),
        h("p", { class: "lap-title__time num" }, U.fmtLapTime(lap.lap_time)),
        h("p", { class: "lap-title__facts" },
          h("span", null, KIND[lap.kind] || lap.kind),
          lap.valid ? signal("green", "Valid", "signal--quiet") : signal("warning", lap.invalid_reason || "Not valid", "signal--quiet"),
          isBest ? h("span", { class: "signal signal--quiet" }, flag("chequered"), h("span", null, "Best in session")) : null,
          best && !isBest && lap.lap_time ? h("span", { class: "num muted" }, `${U.fmtDelta(lap.lap_time - best.lap_time)} to best`) : null)),
      h("div", { class: "lap-tools" },
        h("div", { class: "field" }, h("label", { for: "vs-lap" }, h("span", { class: "label" }, "Overlay")), vsSelect),
        h("div", { class: "lap-tools__nav" }, nav(prev, "prev"), nav(next, "next"))));

    // metrics
    const m = lap.metrics || analysis?.metrics || {};
    const bal = (v) => (v === null || v === undefined ? "–" : `${v > 0.03 ? "U" : v < -0.03 ? "O" : "N"} ${U.signed(v, 2)}`);
    const cells = [
      ["Top speed", m.max_speed !== undefined ? U.fmtSpeed(m.max_speed, true) : "–"],
      ["Full throttle", m.full_throttle_pct !== undefined ? U.pct(m.full_throttle_pct) : "–"],
      ["Braking", m.braking_pct !== undefined ? U.pct(m.braking_pct) : "–"],
      ["Balance in / mid / out", m.balance ? `${bal(m.balance.entry)} · ${bal(m.balance.mid)} · ${bal(m.balance.exit)}` : "–", "wide"],
      ["Wheelspin", m.wheelspin_events ?? "–"],
      ["Lock-ups front / rear", m.lockups ? `${m.lockups.front} / ${m.lockups.rear}` : "–"],
      ["Bottoming", m.bottoming_events ?? "–"],
      ["On limiter", m.limiter_time_s !== undefined ? `${m.limiter_time_s} s` : "–"],
      ["Tyres avg FL FR RL RR", m.tire_temp_avg ? ["fl", "fr", "rl", "rr"].map((w) => U.fmtTemp(m.tire_temp_avg[w])).join("  ") : "–"],
    ];
    clear(metricsEl).append(h("dl", { class: "metrics__grid", title: "U understeer · O oversteer · N neutral" }, cells.map(([k, v, wide]) => h("div", { class: ["metric", wide && "metric--wide"] }, h("dt", null, k), h("dd", { class: "num" }, String(v))))));

    // charts
    const a = trace;
    const b = vsTrace;
    const labelA = `Lap ${lap.number}`;
    const labelB = vsLap ? `Lap ${vsLap.number}` : null;
    const pct = (v) => `${Math.round(v * 100)}%`;
    clear(chartsEl);
    chartsEl.append(h("div", { class: "lap__legend" },
      h("span", { class: "legend legend--a" }, h("i"), `A: ${labelA} ${U.fmtLapTime(lap.lap_time)}`),
      labelB ? h("span", { class: "legend legend--b" }, h("i"), `B: ${labelB} ${U.fmtLapTime(vsLap.lap_time)}, dashed`) : null));
    const chartHost = h("div", { class: "lap__chartHost" });
    chartsEl.append(chartHost);
    const map = createTrackMap(mapEl, { a, b, where: (analysis?.findings || []).flatMap((f) => f.where || []) });
    charts?.destroy();
    charts = createLapCharts(chartHost, {
      a, b, labelA, labelB,
      onCursor: (d, ia, ib) => map.setCursor(ia, ib),
      charts: [
        { id: "speed", title: "Speed", unit: () => U.speedUnit(), height: 9, series: [{ key: "speed", label: "Speed", short: "", cls: "a", map: (v) => U.speedValue(v) }], format: (v) => Math.round(v).toString() },
        { id: "pedals", title: "Throttle and brake", height: 6, domain: [0, 1], series: [{ key: "throttle", label: "Throttle", short: "Thr", cls: "throttle" }, { key: "brake", label: "Brake", short: "Brk", cls: "brake" }], format: pct },
        { id: "steer", title: "Steering", height: 5, domain: [-1, 1], zero: true, series: [{ key: "steer", label: "Steer", short: "", cls: "a" }], format: (v) => U.signed(v * 100, 0, "%") },
        { id: "slip", title: "Slip angle, front vs rear", unit: () => "1.0 = grip limit", height: 6.5, zero: false, limits: [1], series: [{ key: "slip_angle_front", label: "Front", short: "F", cls: "front", map: Math.abs }, { key: "slip_angle_rear", label: "Rear", short: "R", cls: "rear", map: Math.abs }], format: (v) => v.toFixed(2) },
        { id: "ratio", title: "Rear slip ratio", unit: () => "above 1 spin, below −1 lock", height: 5, zero: true, limits: [1, -1], series: [{ key: "slip_ratio_rear", label: "Rear", short: "", cls: "a" }], format: (v) => U.signed(v, 2) },
      ],
    });

    findingsEl.replaceWith(renderLapFindings(analysis, (d) => charts.setCursor(d)));
  }

  load();
  return () => {
    alive = false;
    charts?.destroy();
  };
}
