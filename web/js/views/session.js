// Session detail: the analysis (next change, alternatives, findings, limits)
// beside the lap table, with lap comparison and session housekeeping.

import { h, clear, flag, signal } from "../dom.js";
import { icon } from "../icons.js";
import { store } from "../store.js";
import * as U from "../units.js";
import { describeError } from "../api.js";
import { toast } from "../shell.js";
import { renderSessionAnalysis } from "./analysis.js";
import { skeletonTable } from "./sessions.js";

const KIND = { out: "Out lap", flying: "Flying", in: "In lap", partial: "Partial" };

export function mount(main, ctx, route) {
  const { api } = ctx;
  const id = route.params.id;
  let alive = true;
  let session = null;
  let schemaByKey = null;

  const crumbs = h("nav", { class: "crumbs", "aria-label": "Breadcrumb" }, h("a", { href: "#/sessions" }, "Sessions"), h("span", { "aria-hidden": "true" }, "/"), h("span", null, `Session ${id}`));
  const head = h("div", { class: "session-head" }, h("h1", null, `Session ${id}`));
  const plate = h("div", { class: "session-plate" });
  const danger = h("div", { class: "session__danger" });
  const analysisCol = h("div", { class: "session__analysis scroll-panel", tabindex: "0", "aria-label": "Analysis" }, h("span", { class: "skeleton", style: { height: "14rem" } }));
  const lapsCol = h("div", { class: "session__laps scroll-panel" }, skeletonTable(6));
  const view = h("div", { class: "view session-view" },
    h("div", { class: "view__top" }, h("div", null, crumbs, head), danger),
    plate,
    h("div", { class: "session-grid" }, analysisCol, lapsCol));
  main.append(view);

  async function loadSession() {
    try {
      const [s, schema] = await Promise.all([
        api.session(id),
        schemaByKey ? null : api.tuneSchema().catch(() => null),
      ]);
      if (!alive) return;
      session = s;
      if (schema) schemaByKey = new Map(schema.map((x) => [x.key, x]));
      renderHead();
      renderLaps();
      renderDanger();
    } catch (e) {
      if (!alive) return;
      clear(main).append(h("div", { class: "notice notice--error" },
        e.status === 404 ? `Session ${id} not found` : `Not loaded: ${describeError(e)}`));
    }
  }

  async function loadAnalysis() {
    try {
      const an = await api.sessionAnalysis(id);
      if (!alive) return;
      clear(analysisCol).append(renderSessionAnalysis(an, { schemaByKey }));
    } catch (e) {
      if (!alive) return;
      clear(analysisCol).append(h("div", { class: "notice notice--error" }, `No analysis: ${describeError(e)}`));
    }
  }

  function renderHead() {
    const s = session;
    const recording = store.get("status")?.recording;
    const isRec = recording?.active && String(recording.session_id) === String(s.id);
    clear(head).append(
      h("h1", null, `Session ${s.id}`),
      h("span", { class: "session-head__date num" }, `${U.fmtDate(s.started_at)}${s.stopped_at ? ` to ${U.fmtClock(s.stopped_at)}` : ""}`),
      isRec ? h("span", { class: "tag tag--rec" }, "Recording") : null);
    const note = h("input", { class: "input", id: "session-note", name: "note", autocomplete: "off", value: s.note || "" });
    const noteState = h("span", { class: "field-state", "aria-live": "polite" });
    let saved = s.note || "";
    const saveNote = async () => {
      if (note.value === saved) return;
      noteState.textContent = "Saving…";
      try {
        await api.patchSession(s.id, { note: note.value });
        saved = note.value;
        noteState.textContent = "Saved";
      } catch (e) {
        noteState.textContent = "";
        toast(`Note not saved: ${describeError(e)}`, { kind: "error" });
      }
    };
    note.addEventListener("blur", saveNote);
    note.addEventListener("keydown", (e) => { if (e.key === "Enter") note.blur(); });
    clear(plate).append(
      h("dl", { class: "session-plate__facts" },
        h("div", null, h("dt", null, "Car"), h("dd", null, h("span", { class: "classbadge" }, U.carClass(s.car_class)), ` ${s.car_pi ?? "–"} · ${s.drivetrain ?? "–"}`, h("span", { class: "muted" }, ` · #${s.car_ordinal ?? "?"}`))),
        h("div", null, h("dt", null, "Track"), h("dd", null, U.trackLabel(s.track_ordinal))),
        h("div", null, h("dt", null, "Best"), h("dd", { class: "num" }, U.fmtLapTime(s.best_lap)))),
      h("div", { class: "field session-plate__note" }, h("label", { for: "session-note" }, h("span", { class: "label" }, "Note "), noteState), note));
  }

  function renderLaps() {
    const laps = session.laps || [];
    clear(lapsCol);
    if (!laps.length) {
      lapsCol.append(h("h2", { class: "block-title" }, "Laps"));
      lapsCol.append(h("div", { class: "empty" }, h("p", null, "No laps")));
      return;
    }
    const valid = laps.filter((l) => l.valid && l.kind === "flying" && l.lap_time);
    const best = valid.length ? Math.min(...valid.map((l) => l.lap_time)) : null;
    const picked = new Set();
    const compareBtn = h("button", { class: "btn", type: "button", disabled: true }, icon("overlay"), h("span", null, "Compare 0/2"));
    const updateCompare = () => {
      const ids = [...picked];
      compareBtn.disabled = ids.length !== 2;
      compareBtn.lastChild.textContent = ids.length === 2
        ? `Compare laps ${laps.find((l) => l.id === ids[0]).number} and ${laps.find((l) => l.id === ids[1]).number}`
        : `Compare ${ids.length}/2`;
    };
    compareBtn.addEventListener("click", () => {
      const ids = [...picked];
      if (ids.length === 2) location.hash = `#/laps/${ids[0]}?vs=${ids[1]}`;
    });
    const rows = laps.map((l) => {
      const isBest = best !== null && l.lap_time === best && l.valid;
      const cb = h("input", { type: "checkbox", class: "check", "aria-label": `Compare lap ${l.number}` });
      cb.addEventListener("change", () => {
        if (cb.checked) {
          picked.add(l.id);
          if (picked.size > 2) {
            const first = [...picked][0];
            picked.delete(first);
            const other = tbody.querySelector(`input[data-lap="${first}"]`);
            if (other) other.checked = false;
          }
        } else picked.delete(l.id);
        updateCompare();
      });
      cb.dataset.lap = l.id;
      const href = `#/laps/${l.id}`;
      return h("tr", { class: ["is-link", isBest && "is-best"], onclick: (e) => { if (!e.target.closest("a, input, label")) location.hash = href; } },
        h("td", null, h("a", { class: "row-link num", href }, `Lap ${l.number}`)),
        h("td", null, KIND[l.kind] || l.kind),
        h("td", { class: "r num strong" }, U.fmtLapTime(l.lap_time), isBest ? h("span", { class: "best-mark" }, flag("chequered"), h("span", null, "Best")) : null),
        h("td", { class: "r num" }, l.lap_time && best && !isBest ? U.fmtDelta(l.lap_time - best) : ""),
        h("td", null, l.valid ? signal("green", "Valid", "signal--quiet") : signal("warning", l.invalid_reason || "Not valid", "signal--quiet")),
        h("td", { class: "r" }, h("label", { class: "check-wrap" }, cb)));
    });
    const tbody = h("tbody", null, rows);
    lapsCol.append(
      h("div", { class: "table-wrap" }, h("table", { class: "table laps-table" },
        h("thead", null, h("tr", null,
          h("th", { scope: "col" }, "Lap"), h("th", { scope: "col" }, "Kind"), h("th", { scope: "col", class: "r" }, "Time"),
          h("th", { scope: "col", class: "r" }, "Gap"), h("th", { scope: "col" }, "Valid"), h("th", { scope: "col", class: "r" }, "Compare"))),
        tbody)),
      h("div", { class: "laps-actions" }, compareBtn));
    lapsCol.prepend(h("h2", { class: "block-title" }, "Laps ", h("span", { class: "muted num" }, `(${laps.length})`)));
  }

  function renderDanger() {
    const btn = h("button", { class: "btn btn--danger btn--sm", type: "button" }, icon("trash"), h("span", null, "Delete session"));
    const confirm = h("div", { class: "confirm", hidden: true },
      h("span", null, `Delete session ${session.id}, ${session.laps?.length ?? 0} laps?`),
      h("button", { class: "btn btn--danger btn--sm", type: "button", onclick: async () => {
        try {
          await api.deleteSession(session.id);
          toast(`Session ${session.id} deleted`);
          location.hash = "#/sessions";
        } catch (e) {
          toast(describeError(e), { kind: "error" });
        }
      } }, "Delete"),
      h("button", { class: "btn btn--quiet btn--sm", type: "button", onclick: () => { confirm.hidden = true; btn.hidden = false; btn.focus(); } }, "Cancel"));
    btn.addEventListener("click", () => {
      btn.hidden = true;
      confirm.hidden = false;
      confirm.querySelector("button").focus();
    });
    clear(danger).append(btn, confirm);
  }

  loadSession().then(() => alive && session && loadAnalysis());
  const off1 = store.on("lapCompleted", (m) => { if (String(m.session_id) === String(id)) loadSession(); });
  const off2 = store.on("analysisReady", (m) => { if (String(m.session_id) === String(id)) loadAnalysis(); });
  return () => {
    alive = false;
    off1();
    off2();
  };
}
