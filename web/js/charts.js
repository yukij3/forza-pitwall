// Hand-rolled SVG charts for lap traces: stacked charts against distance with
// one linked cursor, handling events drawn as bands whose length is their
// duration and whose fill is their type, and a track map from pos_x/pos_z.

import { h, s, clear, setText } from "./dom.js";
import * as U from "./units.js";

const PAD_L = 0; // plot spans the full width; labels sit in the chart header

function bisect(arr, x) {
  let lo = 0, hi = arr.length - 1;
  if (hi < 0) return -1;
  if (x <= arr[0]) return 0;
  if (x >= arr[hi]) return hi;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < x) lo = mid;
    else hi = mid;
  }
  return x - arr[lo] < arr[hi] - x ? lo : hi;
}

/** Ranges along distance where a predicate holds, merged across short gaps. */
export function eventRanges(trace, pred, minGap = 15) {
  const out = [];
  const d = trace.distance;
  let start = null;
  for (let i = 0; i < d.length; i++) {
    const on = pred(i);
    if (on && start === null) start = d[i];
    if (!on && start !== null) {
      const prev = out[out.length - 1];
      if (prev && start - prev[1] < minGap) prev[1] = d[i - 1];
      else out.push([start, d[i - 1]]);
      start = null;
    }
  }
  if (start !== null) out.push([start, d[d.length - 1]]);
  return out.map(([a, b]) => [a, Math.max(b, a + 4)]);
}

export function lapEvents(tr) {
  const abs = Math.abs;
  return [
    { key: "understeer", label: "Understeer", ranges: eventRanges(tr, (i) => abs(tr.slip_angle_front[i]) > 1 && abs(tr.slip_angle_front[i]) > abs(tr.slip_angle_rear[i]) + 0.1) },
    { key: "oversteer", label: "Oversteer", ranges: eventRanges(tr, (i) => abs(tr.slip_angle_rear[i]) > 1 && abs(tr.slip_angle_rear[i]) > abs(tr.slip_angle_front[i]) + 0.1) },
    { key: "wheelspin", label: "Wheelspin", ranges: eventRanges(tr, (i) => tr.slip_ratio_rear[i] > 1) },
    { key: "lockup", label: "Rear lock-up", ranges: eventRanges(tr, (i) => tr.slip_ratio_rear[i] < -1) },
  ];
}

/**
 * charts: [{ id, title, unit, height(rem), domain:[min,max]|null, zero:boolean, limits:[values],
 *            series:[{ key, label, cls, map?(v) }] }]
 */
export function createLapCharts(root, { a, b, labelA, labelB, charts, onCursor }) {
  clear(root);
  const maxD = Math.max(a.distance[a.distance.length - 1] || 1, b ? b.distance[b.distance.length - 1] || 1 : 0);
  const events = lapEvents(a);

  const readouts = [];
  const items = charts.map((c) => {
    const svg = s("svg", { class: "chart__svg", preserveAspectRatio: "none", "aria-hidden": "true" });
    const read = h("span", { class: "chart__read num" });
    readouts.push(read);
    const el = h("div", { class: "chart", style: { "--grow": String(c.height) } },
      h("div", { class: "chart__head" },
        h("span", { class: "chart__title" }, c.title, c.unit ? h("span", { class: "chart__unit" }, ` ${c.unit()}`) : null),
        h("span", { class: "chart__legend" }, c.series.map((sr) => h("span", { class: `legend legend--${sr.cls}` }, h("i"), sr.label))),
        read),
      svg);
    return { ...c, svg, el, read };
  });

  // event lane
  const evSvg = s("svg", { class: "events__svg", preserveAspectRatio: "none", "aria-hidden": "true" });
  const evLegend = h("span", { class: "chart__legend" }, events.map((e) =>
    h("span", { class: `legend legend--ev-${e.key}` }, h("i"), `${e.label} `, h("span", { class: "muted num" }, `×${e.ranges.length}`))));
  const evEl = h("div", { class: "chart chart--events" },
    h("div", { class: "chart__head" }, h("span", { class: "chart__title" }, "Events, lap A"), evLegend), evSvg);

  const axis = h("div", { class: "chart__axis num", "aria-hidden": "true" });
  const cursorLabel = h("span", { class: "sr-only", "aria-live": "polite" });
  const stack = h("div", {
    class: "charts", tabindex: "0", role: "group",
    "aria-label": "Lap charts against distance. Left and right arrow keys move the cursor.",
  }, evEl, items.map((i) => i.el), axis, cursorLabel);
  root.append(stack);

  let width = 0;
  let cursorD = null;

  function yScale(c, H) {
    let [min, max] = c.domain || [Infinity, -Infinity];
    if (!c.domain) {
      for (const sr of c.series) {
        for (const tr of [a, b]) {
          if (!tr) continue;
          for (const v0 of tr[sr.key]) {
            const v = sr.map ? sr.map(v0) : v0;
            if (v < min) min = v;
            if (v > max) max = v;
          }
        }
      }
      const pad = (max - min) * 0.08 || 1;
      min -= pad;
      max += pad;
    }
    return (v) => H - ((v - min) / (max - min)) * (H - 6) - 3;
  }

  function pathFor(tr, sr, W, H, y) {
    const d = tr.distance;
    const vals = tr[sr.key];
    if (!vals) return "";
    const step = Math.max(1, Math.floor(d.length / (W * 1.5)));
    let p = "";
    for (let i = 0; i < d.length; i += step) {
      const x = PAD_L + (d[i] / maxD) * (W - PAD_L);
      const v = sr.map ? sr.map(vals[i]) : vals[i];
      p += `${i ? "L" : "M"}${x.toFixed(1)} ${y(v).toFixed(1)}`;
    }
    return p;
  }

  function render() {
    width = stack.clientWidth;
    if (!width) return;
    const W = width;
    for (const c of items) {
      const H = c.svg.clientHeight || 100;
      c.svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      clear(c.svg);
      const y = yScale(c, H);
      // grid: zero line and limit lines
      if (c.zero) c.svg.append(s("line", { class: "grid grid--zero", x1: 0, x2: W, y1: y(0), y2: y(0) }));
      for (const lim of c.limits || []) c.svg.append(s("line", { class: "grid grid--limit", x1: 0, x2: W, y1: y(lim), y2: y(lim) }));
      // distance ticks
      for (let dd = 500; dd < maxD; dd += 500) {
        const x = (dd / maxD) * W;
        c.svg.append(s("line", { class: "grid", x1: x, x2: x, y1: 0, y2: H }));
      }
      if (b) for (const sr of c.series) c.svg.append(s("path", { class: `series series--${sr.cls} series--b`, d: pathFor(b, sr, W, H, y) }));
      for (const sr of c.series) c.svg.append(s("path", { class: `series series--${sr.cls}`, d: pathFor(a, sr, W, H, y) }));
      c.cursor = s("line", { class: "cursor", x1: -10, x2: -10, y1: 0, y2: H });
      c.svg.append(c.cursor);
      c.y = y;
      c.H = H;
    }
    // events lane: one row per event type
    const EH = evSvg.clientHeight || 32;
    evSvg.setAttribute("viewBox", `0 0 ${W} ${EH}`);
    clear(evSvg);
    const rowH = EH / events.length;
    events.forEach((e, row) => {
      for (const [d0, d1] of e.ranges) {
        evSvg.append(s("rect", { class: `ev ev--${e.key}`, x: (d0 / maxD) * W, width: Math.max(2, ((d1 - d0) / maxD) * W), y: row * rowH + 1, height: rowH - 2 }));
      }
    });
    evEl.cursor = s("line", { class: "cursor", x1: -10, x2: -10, y1: 0, y2: EH });
    evSvg.append(evEl.cursor);
    // axis labels
    clear(axis);
    for (let dd = 0; dd <= maxD; dd += 500) {
      axis.append(h("span", { style: { left: `${(dd / maxD) * 100}%` } }, U.fmtDistance(dd)));
    }
    if (cursorD !== null) setCursor(cursorD, false);
  }

  function setCursor(dist, notify = true) {
    cursorD = Math.max(0, Math.min(maxD, dist));
    const x = (cursorD / maxD) * width;
    const ia = bisect(a.distance, cursorD);
    const ib = b ? bisect(b.distance, cursorD) : -1;
    for (const c of items) {
      if (c.cursor) {
        c.cursor.setAttribute("x1", x);
        c.cursor.setAttribute("x2", x);
      }
      const parts = c.series.map((sr) => {
        const fmt = (tr, i) => {
          if (!tr || i < 0) return "–";
          const v = sr.map ? sr.map(tr[sr.key][i]) : tr[sr.key][i];
          return c.format ? c.format(v) : v.toFixed(2);
        };
        return `${sr.short ?? sr.label} ${fmt(a, ia)}${b ? ` / ${fmt(b, ib)}` : ""}`;
      });
      setText(c.read, parts.join("  ·  "));
    }
    if (evEl.cursor) {
      evEl.cursor.setAttribute("x1", x);
      evEl.cursor.setAttribute("x2", x);
    }
    if (notify && onCursor) onCursor(cursorD, ia, ib);
  }

  function fromEvent(e) {
    const rect = stack.getBoundingClientRect();
    return ((e.clientX - rect.left) / rect.width) * maxD;
  }
  stack.addEventListener("pointermove", (e) => setCursor(fromEvent(e)));
  stack.addEventListener("pointerdown", (e) => setCursor(fromEvent(e)));
  stack.addEventListener("keydown", (e) => {
    const step = maxD * (e.shiftKey ? 0.05 : 0.01);
    if (e.key === "ArrowRight") setCursor((cursorD ?? 0) + step);
    else if (e.key === "ArrowLeft") setCursor((cursorD ?? 0) - step);
    else if (e.key === "Home") setCursor(0);
    else if (e.key === "End") setCursor(maxD);
    else return;
    e.preventDefault();
    setText(cursorLabel, `${U.fmtDistance(cursorD)}. ${items.map((c) => `${c.title}: ${c.read.textContent}`).join(". ")}`);
  });

  const ro = new ResizeObserver(() => render());
  ro.observe(stack);
  render();
  setCursor(maxD * 0.25, true);

  return {
    setCursor,
    destroy: () => ro.disconnect(),
    labelA,
    labelB,
  };
}

/** Track map from pos_x/pos_z with event segments and cursor dots. */
export function createTrackMap(root, { a, b, where = [] }) {
  clear(root);
  const xs = a.pos_x, zs = a.pos_z;
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for (let i = 0; i < xs.length; i++) {
    if (xs[i] < minX) minX = xs[i];
    if (xs[i] > maxX) maxX = xs[i];
    if (zs[i] < minZ) minZ = zs[i];
    if (zs[i] > maxZ) maxZ = zs[i];
  }
  const pad = 40;
  const w = maxX - minX + pad * 2;
  const hgt = maxZ - minZ + pad * 2;
  // Game Z is forward/north; flip so the map reads like a circuit diagram.
  const px = (x) => x - minX + pad;
  const pz = (z) => maxZ - z + pad;
  const sw = Math.max(w, hgt) / 90;
  const pts = (tr, i0 = 0, i1 = tr.pos_x.length - 1) => {
    const out = [];
    const step = Math.max(1, Math.floor((i1 - i0) / 900));
    for (let i = i0; i <= i1; i += step) out.push(`${px(tr.pos_x[i]).toFixed(1)},${pz(tr.pos_z[i]).toFixed(1)}`);
    return out.join(" ");
  };
  const svg = s("svg", { class: "trackmap__svg", viewBox: `0 0 ${w} ${hgt}`, role: "img", "aria-label": "Track map drawn from this lap's positions" });
  svg.append(s("polyline", { class: "track track--base", points: pts(a), "stroke-width": sw * 2.2 }));
  svg.append(s("polyline", { class: "track track--line", points: pts(a), "stroke-width": sw * 0.5 }));
  for (const e of lapEvents(a)) {
    for (const [d0, d1] of e.ranges) {
      const i0 = bisect(a.distance, d0), i1 = bisect(a.distance, d1);
      if (i1 <= i0) continue;
      svg.append(s("polyline", { class: `track-ev track-ev--${e.key}`, points: pts(a, i0, i1), "stroke-width": sw * 1.3 }));
    }
  }
  // start/finish
  if (xs.length > 2) {
    svg.append(s("circle", { class: "sf", cx: px(xs[0]), cy: pz(zs[0]), r: sw * 1.6 }));
  }
  for (const wh of where) {
    const i = bisect(a.distance, wh.distance);
    if (i < 0) continue;
    const g = s("g", { class: "corner-tag" },
      s("circle", { cx: px(xs[i]), cy: pz(zs[i]), r: sw * 3.2 }),
      s("text", { x: px(xs[i]), y: pz(zs[i]), "font-size": sw * 3.6, "dominant-baseline": "central", "text-anchor": "middle" }, String(wh.corner ?? "•")));
    svg.append(g);
  }
  const dotB = b ? s("circle", { class: "dot dot--b", r: sw * 2, cx: -100, cy: -100, "stroke-width": sw * 0.8 }) : null;
  const dotA = s("circle", { class: "dot dot--a", r: sw * 2, cx: -100, cy: -100 });
  if (dotB) svg.append(dotB);
  svg.append(dotA);
  root.append(svg);
  return {
    setCursor(ia, ib) {
      if (ia >= 0) {
        dotA.setAttribute("cx", px(xs[ia]));
        dotA.setAttribute("cy", pz(zs[ia]));
      }
      if (dotB && b && ib >= 0) {
        dotB.setAttribute("cx", px(b.pos_x[ib]));
        dotB.setAttribute("cy", pz(b.pos_z[ib]));
      }
    },
  };
}
