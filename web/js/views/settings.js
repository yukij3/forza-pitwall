// Settings: display units, auto-record, the Data Out values for the game,
// and the flag code used across the UI.

import { h, clear, flag } from "../dom.js";
import { store } from "../store.js";
import { setUnits } from "../units.js";
import { describeError } from "../api.js";
import { dataOutRows } from "./setup.js";

const UNIT_GROUPS = [
  ["speed", "Speed", [["kmh", "km/h"], ["mph", "mph"]]],
  ["temperature", "Temperature", [["C", "°C"], ["F", "°F"]]],
  ["pressure", "Tyre pressure", [["psi", "psi"], ["bar", "bar"]]],
];

const FLAGS = [
  ["green", "Green", "Data flowing"],
  ["yellow", "Yellow", "Waiting, menus"],
  ["red", "Red", "Server or receiver down"],
  ["meatball", "Black, orange disc", "Next change"],
  ["chequered", "Chequered", "Best lap"],
  ["warning", "Black and white", "Lap not valid"],
  ["slippery", "Yellow and red stripes", "Wheelspin or lock-up"],
];
const PLATES = [
  ["ok", "OK", "Inside target"],
  ["warn", "Watch", "Drifting"],
  ["bad", "Fix", "Well off target"],
  ["collecting", "Collecting", "Too few samples"],
];

export function mount(main, ctx) {
  const { api } = ctx;
  let alive = true;
  const state = h("span", { class: "field-state", role: "status", "aria-live": "polite" });
  const unitsEl = h("div", { class: "settings__units" }, h("span", { class: "skeleton", style: { height: "8rem" } }));
  const autoEl = h("div");
  const dataOutEl = h("div");

  main.append(h("div", { class: "view" },
    h("div", { class: "view__top" }, h("h1", null, "Settings")),
    h("div", { class: "settings-grid" },
      h("div", { class: "settings-col" },
      h("section", { class: "panel", "aria-labelledby": "units-title" },
        h("div", { class: "panel__head" }, h("h2", { id: "units-title", class: "panel__title" }, "Units"), state),
        h("div", { class: "panel__body" }, unitsEl, autoEl)),
      h("section", { class: "panel", "aria-labelledby": "about-title" },
        h("div", { class: "panel__head" }, h("h2", { id: "about-title", class: "panel__title" }, "About")),
        h("div", { class: "panel__body settings__about" },
          h("p", null, "Not affiliated with Microsoft or Turn 10 Studios."),
          ctx.mock ? h("p", { class: "notice notice--warn" }, flag("yellow"), h("span", null, "Demo: simulated, not saved")) : null))),
      h("section", { class: "panel", "aria-labelledby": "dataout-title" },
        h("div", { class: "panel__head" }, h("h2", { id: "dataout-title", class: "panel__title" }, "Data Out")),
        h("div", { class: "panel__body" },
          h("p", { class: "setup__path" }, "Settings", h("span", { class: "arrow" }, "→"), "Gameplay & HUD", h("span", { class: "arrow" }, "→"), "Data Out"),
          dataOutEl)),
      h("section", { class: "panel", "aria-labelledby": "flags-title" },
        h("div", { class: "panel__head" }, h("h2", { id: "flags-title", class: "panel__title" }, "Flag code")),
        h("div", { class: "panel__body" },
          h("dl", { class: "flagcode" },
            FLAGS.map(([k, name, meaning]) => h("div", null, h("dt", null, flag(k), h("span", null, name)), h("dd", null, meaning))),
            PLATES.map(([k, word, meaning]) => h("div", null, h("dt", null, h("span", { class: `plate plate--${k} plate--inline` }, word)), h("dd", null, meaning)))))))));

  function renderUnits(settings) {
    clear(unitsEl);
    for (const [key, label, options] of UNIT_GROUPS) {
      const name = `unit-${key}`;
      unitsEl.append(h("div", { class: "field settings__row", role: "radiogroup", "aria-labelledby": `${name}-label` },
        h("span", { class: "label", id: `${name}-label` }, label),
        h("div", { class: "segmented" }, options.map(([v, text]) => h("label", null,
          h("input", { type: "radio", name, value: v, checked: settings.units[key] === v, onchange: () => save({ units: { ...settings.units, [key]: v } }) }),
          h("span", null, text))))));
    }
    clear(autoEl);
    const sw = h("input", { type: "checkbox", role: "switch", id: "auto-record", checked: !!settings.auto_record, "aria-describedby": "auto-record-help" });
    const word = h("span", { class: "state" }, settings.auto_record ? "On" : "Off");
    sw.addEventListener("change", () => save({ ...settings, auto_record: sw.checked }));
    autoEl.append(h("div", { class: "settings__auto" },
      h("label", { class: "switch", for: "auto-record", title: "Starts on track, stops after 30 s in menus" }, sw, h("span", null, "Auto-record"), word),
      h("span", { id: "auto-record-help", class: "sr-only" }, "Starts on track, stops after 30 s in menus")));
  }

  async function save(next) {
    const current = store.get("settings");
    const body = { ...current, ...next, units: { ...current.units, ...(next.units || {}) } };
    state.textContent = "Saving…";
    try {
      const saved = await api.saveSettings(body);
      if (!alive) return;
      setUnits(saved.units);
      store.set("settings", saved);
      renderUnits(saved);
      state.textContent = "Saved";
    } catch (e) {
      if (!alive) return;
      state.textContent = "";
      renderUnits(current);
      unitsEl.prepend(h("p", { class: "notice notice--error" }, `Not saved: ${describeError(e)}`));
    }
  }

  function renderDataOut() {
    clear(dataOutEl).append(dataOutRows(store.get("status")));
  }

  const s = store.get("settings");
  if (s) renderUnits(s);
  else api.settings().then((x) => { if (alive) { store.set("settings", x); renderUnits(x); } })
    .catch((e) => { if (alive) clear(unitsEl).append(h("p", { class: "notice notice--error" }, `Not loaded: ${describeError(e)}`)); });
  renderDataOut();
  let lastHost = null;
  const off = store.on("status", (st) => {
    const key = `${st?.receiver?.public_host}|${st?.receiver?.udp_port}`;
    if (key !== lastHost) { lastHost = key; renderDataOut(); }
  });
  return () => {
    alive = false;
    off();
  };
}
