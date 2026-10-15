// Baseline: approximate starting values for the car type on track, laid out
// in the game's tuning-menu order. Read-only. A category can be picked by
// hand (#/baseline?category=gt3) when the match is wrong or no car is on track.

import { h, clear, gameText } from "../dom.js";
import { store } from "../store.js";
import * as U from "../units.js";
import { describeError } from "../api.js";

const HOW = { ordinal: "Car model", division: "Division", class_drivetrain: "Class + drivetrain" };
const LEVEL = { high: "High", medium: "Medium", low: "Low" };

const decimalsOf = (v) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return 0;
  const s = String(Math.round(n * 100) / 100);
  return s.includes(".") ? s.split(".")[1].length : 0;
};

/** Decimals for a row: as precise as its value or range, and at least the game's own step for the unit. */
function rowDecimals(r) {
  const min = r.unit === "psi" || r.unit === "°" || r.unit === "in" ? 1 : r.unit === "bar" ? 2 : 0;
  return Math.max(min, decimalsOf(r.value), ...(Array.isArray(r.range) ? r.range.map(decimalsOf) : [0]));
}

function num(v, d) {
  if (v === null || v === undefined) return "";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return U.minus(n.toFixed(d));
}

function withUnit(v, unit, d) {
  const s = num(v, d);
  if (!unit) return s;
  if (unit === "°") return `${s}°`;
  if (unit.startsWith("%")) return `${s}%${unit.slice(1)}`;
  return `${s} ${unit}`;
}

/** "≈ 60% of slider" → 60, for drawing the slider position. */
function sliderPct(relative) {
  const m = String(relative || "").match(/(\d+(?:\.\d+)?)\s*%\s*of\s+(?:the\s+)?slider/i);
  return m ? Math.min(100, Math.max(0, Number(m[1]))) : null;
}

/** In-game style slider track with the suggested position marked. */
function sliderTrack(pct) {
  return h("span", { class: "base-slider", "aria-hidden": "true" },
    h("i", { class: "base-slider__fill", style: { width: `${pct}%` } }),
    h("i", { class: "base-slider__mark", style: { left: `${pct}%` } }));
}

const SHORT_NOTE_WORDS = 4;
function noteCell(note) {
  if (!note) return h("td", { class: "base-row__note" });
  const text = U.minus(note);
  if (text.trim().split(/\s+/).length <= SHORT_NOTE_WORDS) return h("td", { class: "base-row__note" }, gameText(text));
  // Longer notes live in a tooltip on desktop; phones have room to show them in full.
  return h("td", { class: "base-row__note" },
    h("span", { class: "base-note", title: text, tabindex: "0" }, h("span", { class: "base-note__short" }, "Note"), h("span", { class: "base-note__full" }, gameText(text))));
}

function rangeText(range, d) {
  if (!Array.isArray(range) || range.length !== 2) return "";
  return `${num(range[0], d)} … ${num(range[1], d)}`;
}

/** Group settings into sections, keeping server (menu) order. */
function sections(settings) {
  const out = [];
  for (const s of settings || []) {
    let sec = out[out.length - 1];
    if (!sec || sec.name !== s.section) out.push((sec = { name: s.section, rows: [] }));
    sec.rows.push(s);
  }
  return out;
}

function sheet(baseline) {
  return h("div", { class: "base-sheet" }, sections(baseline.settings).map((sec) => {
    let lastLabel = null;
    // One precision per unit within a section, so Front and Rear columns line up.
    const dec = new Map();
    for (const r of sec.rows) dec.set(r.unit, Math.max(dec.get(r.unit) ?? 0, rowDecimals(r)));
    return h("section", { class: "base-sec" },
      h("h2", { class: "base-sec__title" }, sec.name),
      h("table", { class: "base-table" },
        h("thead", { class: "sr-only" }, h("tr", null,
          h("th", { scope: "col" }, "Setting"), h("th", { scope: "col" }, "Axle"), h("th", { scope: "col" }, "Value"),
          h("th", { scope: "col" }, "Range"), h("th", { scope: "col" }, "Note"))),
        h("tbody", null, sec.rows.map((r) => {
          const label = r.label === sec.name ? "" : r.label;
          const showLabel = label !== lastLabel;
          lastLabel = label;
          const hasValue = r.value !== null && r.value !== undefined;
          const d = dec.get(r.unit);
          return h("tr", { class: ["base-row", showLabel && "is-first"], dataset: { key: r.key } },
            h("th", { scope: "row", class: "base-row__label" }, showLabel ? label : h("span", { class: "sr-only" }, label)),
            h("td", { class: "base-row__axle" }, r.axle || ""),
            hasValue
              ? h("td", { class: "base-row__value num" }, withUnit(r.value, r.unit, d))
              : h("td", { class: "base-row__value base-row__value--rel" }, r.relative ? U.minus(r.relative) : "–"),
            hasValue
              ? h("td", { class: "base-row__range num", title: r.range ? "Range" : null }, rangeText(r.range, d))
              : h("td", { class: "base-row__range" }, sliderPct(r.relative) !== null ? sliderTrack(sliderPct(r.relative)) : ""),
            noteCell(r.note));
        }))));
  }));
}

export function mount(main, ctx, route) {
  const { api } = ctx;
  let alive = true;
  let categories = null;
  const pick = route?.query?.category || "";

  const select = h("select", { class: "select", id: "base-cat", "aria-label": "Category" });
  select.addEventListener("change", () => {
    location.hash = select.value ? `#/baseline?category=${encodeURIComponent(select.value)}` : "#/baseline";
  });
  const facts = h("dl", { class: "base-facts" });
  const notes = h("div", { class: "base-notes" });
  const body = h("div", { class: "base-main" }, h("span", { class: "skeleton", style: { height: "20rem" } }));
  const title = h("span", { class: "base-kicker" }, "Starting point");

  main.append(h("div", { class: "view base-view" },
    h("div", { class: "view__top" },
      h("div", { class: "view__title" }, h("h1", null, "Baseline"), title),
      h("div", { class: "inline-field" }, h("label", { class: "label", for: "base-cat" }, "Category"), select)),
    h("div", { class: "base-grid" }, body, h("aside", { class: "base-side", "aria-label": "Match and sources" }, facts, notes))));

  function renderSelect(matchId) {
    clear(select).append(
      h("option", { value: "", selected: !pick }, matchId ? `Auto: ${(categories || []).find((c) => c.id === matchId)?.name ?? matchId}` : "Auto"),
      (categories || []).map((c) => h("option", { value: c.id, selected: c.id === pick }, c.name)));
  }

  function fact(k, v, attrs) {
    return h("div", attrs, h("dt", null, k), h("dd", null, v));
  }

  function renderSide(baseline, match) {
    const car = match?.car || null;
    const st = store.get("status")?.car;
    clear(facts).append(
      fact("Car", car?.name || (st ? `${U.carLabel(st)} · ${st.drivetrain}` : "None on track"), { class: "base-facts__car" }),
      car?.division ? fact("Division", car.division) : null,
      fact("Category", baseline ? baseline.category.name : "–"),
      pick ? fact("Match", "Manual") : match ? fact("Match", `${HOW[match.how] || match.how} · ${LEVEL[match.confidence] || match.confidence}`) : null,
      baseline ? fact("Confidence", LEVEL[baseline.confidence] || baseline.confidence) : null,
      baseline ? fact("Units", baseline.unit_system === "metric" ? "Metric" : "Imperial") : null);
    clear(notes);
    if (!baseline) return;
    if (baseline.notes?.length) notes.append(h("ul", { class: "base-notes__list" }, baseline.notes.map((n) => h("li", null, U.minus(n)))));
    if (baseline.sources?.length) {
      notes.append(h("details", { class: "base-sources" },
        h("summary", null, "Sources ", h("span", { class: "muted num" }, `(${baseline.sources.length})`)),
        h("ul", null, baseline.sources.map((s) => h("li", null,
          s.url ? h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer" }, s.title || s.url) : s.title)))));
    }
  }

  function renderBody(baseline, emptyText) {
    clear(body);
    if (!baseline) {
      body.append(h("div", { class: "empty" }, h("h2", null, emptyText), h("label", { class: "label", for: "base-cat" }, "Pick a category")));
      return;
    }
    body.append(sheet(baseline));
  }

  function fail(e) {
    if (!alive) return;
    clear(body).append(h("div", { class: "notice notice--error" },
      e?.status === 503 ? "Baselines unavailable" : `Not loaded: ${describeError(e)}`));
  }

  async function load() {
    try {
      const [cats, res] = await Promise.all([
        categories ? categories : api.baselineCategories(),
        api.baseline().catch((e) => (e?.status === 503 ? Promise.reject(e) : { match: null, baseline: null })),
      ]);
      if (!alive) return;
      categories = cats;
      const matchId = res?.match?.category_id || null;
      renderSelect(matchId);
      if (pick) {
        const b = await api.baselineFor(pick);
        if (!alive) return;
        renderSide(b, res?.match);
        renderBody(b);
      } else {
        renderSide(res?.baseline || null, res?.match);
        renderBody(res?.baseline || null, store.get("status")?.car ? "No category for this car" : "No car on track");
      }
    } catch (e) {
      fail(e);
    }
  }

  load();
  // Re-match when a different car rolls out.
  let carKey = keyOf(store.get("status")?.car);
  const off = store.on("status", (st) => {
    const k = keyOf(st?.car);
    if (k !== carKey) {
      carKey = k;
      if (!pick) load();
    }
  });
  return () => {
    alive = false;
    off();
  };
}

function keyOf(car) {
  return car ? `${car.ordinal}|${car.class}|${car.drivetrain}` : "";
}
