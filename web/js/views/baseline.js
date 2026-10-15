// Baseline: approximate starting values for the car type on track, laid out
// in the game's tuning-menu order, one row per setting with Front and Rear
// side by side. Read-only. Notes and ranges live in tooltips so the whole
// car fits one screen. A category can be picked by hand
// (#/baseline?category=gt3) when the match is wrong or no car is on track.

import { h, clear } from "../dom.js";
import { store } from "../store.js";
import * as U from "../units.js";
import { describeError } from "../api.js";

const HOW = { ordinal: "Car model", division: "Division", class_drivetrain: "Class + drivetrain" };
const LEVEL = { high: "High", medium: "Medium", low: "Low" };

// ------------------------------------------------------------- formatting

const decimalsOf = (v) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return 0;
  const s = String(Math.round(n * 100) / 100);
  return s.includes(".") ? s.split(".")[1].length : 0;
};

/** Decimals for a setting: as precise as its value or range, at least the game's step for the unit. */
function decimalsFor(s) {
  const min = s.unit === "psi" || s.unit === "°" || s.unit === "in" ? 1 : s.unit === "bar" ? 2 : 0;
  return Math.max(min, decimalsOf(s.value), ...(Array.isArray(s.range) ? s.range.map(decimalsOf) : [0]));
}

function num(v, d) {
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v ?? "");
  return U.minus(n.toFixed(d));
}

function withUnit(v, unit, d) {
  const s = num(v, d);
  if (!unit) return s;
  if (unit === "°") return `${s}°`;
  if (unit.startsWith("%")) return `${s}%${unit.slice(1)}`;
  return `${s} ${unit}`;
}

/** "≈100% of slider (60–100%)" → { pct: 100, lo: 60, hi: 100 }. */
export function parseRelative(text) {
  const t = String(text || "").replace(/−/g, "-");
  const m = t.match(/(\d+(?:\.\d+)?)\s*%\s*of\s+(?:the\s+)?slider/i);
  if (!m) return null;
  const r = t.match(/\(\s*(\d+(?:\.\d+)?)\s*%?\s*(?:–|-|…|to)\s*(\d+(?:\.\d+)?)\s*%\s*\)/);
  const clamp = (x) => Math.min(100, Math.max(0, Number(x)));
  return { pct: clamp(m[1]), lo: r ? clamp(r[1]) : null, hi: r ? clamp(r[2]) : null };
}

const DEFAULT_NOTE = /\b(default|as (?:built|delivered)|the build gives)\b/i;

// ------------------------------------------------------------------ sheet

/**
 * Sections in server (menu) order; inside each, one row per label with the
 * Front and Rear settings side by side. Axle-less settings span both columns.
 */
function sectionsOf(settings) {
  const out = [];
  for (const s of settings || []) {
    let sec = out[out.length - 1];
    if (!sec || sec.name !== s.section) out.push((sec = { name: s.section, rows: [] }));
    let row = sec.rows.find((r) => r.label === s.label && !r.single && s.axle);
    if (!row || (s.axle && row[s.axle.toLowerCase()])) {
      row = { label: s.label, front: null, rear: null, single: null };
      sec.rows.push(row);
    }
    if (s.axle === "Front") row.front = s;
    else if (s.axle === "Rear") row.rear = s;
    else row.single = s;
  }
  return out;
}

/** Tooltip text for a row: notes de-duplicated, range of relative values. */
function rowTip(row) {
  const parts = [];
  const items = [row.single, row.front, row.rear].filter(Boolean);
  const notes = [...new Set(items.map((s) => s.note).filter(Boolean))];
  if (notes.length === 1) parts.push(notes[0]);
  else items.forEach((s) => s.note && parts.push(`${s.axle || s.label}: ${s.note}`));
  return U.minus(parts.join("\n\n"));
}

function valueCell(s, extraClass) {
  if (!s) return h("td", { class: ["base-v", "base-v--none", extraClass] }, h("span", { class: "sr-only" }, "Not set"));
  const d = decimalsFor(s);
  if (s.value !== null && s.value !== undefined) {
    const range = Array.isArray(s.range) ? `${num(s.range[0], d)} … ${num(s.range[1], d)}` : "";
    return h("td", { class: ["base-v", extraClass] },
      h("span", { class: "base-v__main num" }, withUnit(s.value, s.unit, d)),
      range ? h("span", { class: "base-v__range num" }, h("span", { class: "sr-only" }, "range "), range) : null);
  }
  const rel = parseRelative(s.relative);
  if (rel) {
    return h("td", { class: ["base-v", "base-v--rel", extraClass], "data-tip": U.minus(s.relative) },
      h("span", { class: "base-v__main num" }, `${Math.round(rel.pct)}%`, h("span", { class: "sr-only" }, ` of slider${rel.lo !== null ? `, range ${rel.lo} to ${rel.hi}%` : ""}`)),
      h("span", { class: "base-slider", "aria-hidden": "true" },
        rel.lo !== null ? h("i", { class: "base-slider__band", style: { left: `${rel.lo}%`, width: `${Math.max(1, rel.hi - rel.lo)}%` } }) : null,
        h("i", { class: "base-slider__mark", style: { left: `${rel.pct}%` } })));
  }
  if (s.relative) {
    return h("td", { class: ["base-v", "base-v--text", extraClass], "data-tip": U.minus(s.relative) }, h("span", { class: "base-v__main" }, U.minus(s.relative)));
  }
  if (s.note && DEFAULT_NOTE.test(s.note)) {
    return h("td", { class: ["base-v", "base-v--default", extraClass] }, h("span", { class: "base-v__main" }, "Default"));
  }
  return h("td", { class: ["base-v", "base-v--rule", extraClass] }, h("span", { class: "base-v__main" }, "–"), h("span", { class: "sr-only" }, "see note"));
}

function sheet(baseline) {
  return h("div", { class: "base-sheet" }, sectionsOf(baseline.settings).map((sec) => {
    const hasAxles = sec.rows.some((r) => r.front || r.rear);
    return h("section", { class: "base-sec" },
      h("table", { class: "base-table" },
        h("thead", null, h("tr", null,
          h("th", { scope: "col", class: "base-sec__title" }, sec.name),
          hasAxles ? h("th", { scope: "col", class: "base-sec__axle" }, "Front") : h("th", { scope: "col", class: "base-sec__axle" }, h("span", { class: "sr-only" }, "Value")),
          hasAxles ? h("th", { scope: "col", class: "base-sec__axle" }, "Rear") : h("td", { class: "base-sec__axle" }))),
        h("tbody", null, sec.rows.map((row) => {
          const tip = rowTip(row);
          const label = row.label;
          return h("tr", { class: "base-row" },
            h("th", { scope: "row", class: "base-row__label" },
              label ? h("span", { class: "base-row__name" }, label) : h("span", { class: "sr-only" }, row.label),
              tip ? h("button", { class: "base-info", type: "button", "data-tip": tip, "aria-label": `Note: ${tip}` }, "i") : null),
            row.single ? spanCell(valueCell(row.single, "base-v--span")) : null,
            row.single ? null : valueCell(row.front),
            row.single ? null : valueCell(row.rear));
        }))));
  }));
}

/** Axle-less settings (Final Drive, Braking Balance) take both value columns. */
function spanCell(td) {
  td.colSpan = 2;
  return td;
}

// --------------------------------------------------------------- tooltip

/** One floating tooltip for every [data-tip] in the view: hover, focus or tap. */
function createTips(root) {
  const tip = h("div", { class: "base-tip", role: "tooltip", hidden: true });
  document.body.append(tip);
  let owner = null;
  function show(el) {
    owner = el;
    tip.textContent = el.dataset.tip;
    tip.hidden = false;
    const r = el.getBoundingClientRect();
    const tw = tip.offsetWidth;
    const th = tip.offsetHeight;
    const left = Math.min(window.innerWidth - tw - 8, Math.max(8, r.left - 10));
    let top = r.bottom + 8;
    if (top + th > window.innerHeight - 8) top = Math.max(8, r.top - th - 8);
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  }
  function hide() {
    owner = null;
    tip.hidden = true;
  }
  const over = (e) => { const el = e.target.closest?.("[data-tip]"); if (el && root.contains(el)) show(el); };
  const out = (e) => { const el = e.target.closest?.("[data-tip]"); if (el && el === owner && !el.contains(e.relatedTarget)) hide(); };
  const click = (e) => { const el = e.target.closest?.(".base-info"); if (!el) return; if (owner === el) hide(); else show(el); };
  const key = (e) => { if (e.key === "Escape") hide(); };
  root.addEventListener("mouseover", over);
  root.addEventListener("mouseout", out);
  root.addEventListener("focusin", over);
  root.addEventListener("focusout", hide);
  root.addEventListener("click", click);
  document.addEventListener("keydown", key);
  window.addEventListener("scroll", hide, true);
  return () => {
    root.removeEventListener("mouseover", over);
    root.removeEventListener("mouseout", out);
    root.removeEventListener("focusin", over);
    root.removeEventListener("focusout", hide);
    root.removeEventListener("click", click);
    document.removeEventListener("keydown", key);
    window.removeEventListener("scroll", hide, true);
    tip.remove();
  };
}

// ------------------------------------------------------------------- view

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
  const sources = h("div", { class: "base-notes" });
  const body = h("div", { class: "base-main" }, h("span", { class: "skeleton", style: { height: "20rem" } }));
  const kicker = h("span", { class: "base-kicker" }, "Starting point");

  const view = h("div", { class: "view base-view" },
    h("div", { class: "view__top" },
      h("div", { class: "view__title" }, h("h1", null, "Baseline"), kicker),
      h("div", { class: "inline-field" }, h("label", { class: "label", for: "base-cat" }, "Category"), select)),
    h("div", { class: "base-grid" }, body, h("aside", { class: "base-side", "aria-label": "Match and sources" }, facts, sources)));
  main.append(view);
  const destroyTips = createTips(view);

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
      baseline?.drivetrain ? fact("Drivetrain", baseline.drivetrain) : null,
      baseline ? fact("Units", baseline.unit_system === "metric" ? "Metric" : "Imperial") : null);
    // Category notes go behind the "Starting point" label; the sheet stays numbers only.
    if (baseline?.notes?.length) {
      kicker.dataset.tip = U.minus(baseline.notes.join("\n\n"));
      kicker.tabIndex = 0;
    } else {
      delete kicker.dataset.tip;
      kicker.removeAttribute("tabindex");
    }
    clear(sources);
    if (baseline?.sources?.length) {
      sources.append(h("details", { class: "base-sources" },
        h("summary", null, "Sources ", h("span", { class: "muted num" }, `(${baseline.sources.length})`)),
        h("ul", null, baseline.sources.map((s) => h("li", null,
          s.url ? h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", title: s.used_for || null }, s.title || s.url) : s.title)))));
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
    destroyTips();
  };
}

function keyOf(car) {
  return car ? `${car.ordinal}|${car.class}|${car.drivetrain}` : "";
}
