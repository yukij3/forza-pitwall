// Sessions: every Start→Stop recording, newest first, sortable.

import { h, clear } from "../dom.js";
import { icon } from "../icons.js";
import { store } from "../store.js";
import * as U from "../units.js";
import { describeError } from "../api.js";

const COLS = [
  { key: "started_at", label: "Started", sort: (s) => new Date(s.started_at).getTime() },
  { key: "car", label: "Car" },
  { key: "track", label: "Track", sort: (s) => s.track_ordinal ?? -1 },
  { key: "lap_count", label: "Laps", sort: (s) => s.lap_count ?? 0, num: true },
  { key: "best_lap", label: "Best lap", sort: (s) => s.best_lap ?? Infinity, num: true },
  { key: "note", label: "Note" },
];

export function mount(main, ctx) {
  const { api } = ctx;
  const body = h("div", { class: "sessions-body scroll-panel" }, skeletonTable());
  const count = h("span", { class: "count num" });
  main.append(h("div", { class: "view" },
    h("div", { class: "view__top" },
      h("h1", null, "Sessions ", count)),
    body));

  let sessions = [];
  let sortKey = "started_at";
  let dir = -1;
  let alive = true;

  async function load() {
    try {
      const list = await api.sessions();
      if (!alive) return;
      sessions = list;
      render();
    } catch (e) {
      if (!alive) return;
      clear(body).append(h("div", { class: "notice notice--error" }, `Not loaded: ${describeError(e)} `,
        h("button", { class: "btn btn--sm", type: "button", onclick: load }, "Try again")));
    }
  }

  function render() {
    count.textContent = sessions.length ? `(${sessions.length})` : "";
    clear(body);
    if (!sessions.length) {
      body.append(h("div", { class: "empty" },
        h("h2", null, "No sessions"),
        h("a", { class: "btn", href: "#/live" }, "Live", icon("arrowRight"))));
      return;
    }
    const col = COLS.find((c) => c.key === sortKey);
    const sorted = [...sessions].sort((a, b) => (col.sort(a) - col.sort(b)) * dir);
    const recordingId = store.get("status")?.recording?.active ? store.get("status").recording.session_id : null;
    const thead = h("thead", null, h("tr", null, COLS.map((c) => {
      const th = h("th", { scope: "col", class: c.num ? "r" : "" });
      if (c.sort) {
        th.setAttribute("aria-sort", c.key === sortKey ? (dir > 0 ? "ascending" : "descending") : "none");
        th.append(h("button", { class: "th-sort", type: "button", onclick: () => { if (sortKey === c.key) dir = -dir; else { sortKey = c.key; dir = c.key === "best_lap" ? 1 : -1; } render(); } },
          c.label, icon(c.key === sortKey ? (dir > 0 ? "sortAsc" : "sortDesc") : "sort")));
      } else th.textContent = c.label;
      return th;
    })));
    const tbody = h("tbody", null, sorted.map((s) => {
      const href = `#/sessions/${s.id}`;
      const tr = h("tr", { class: "is-link", onclick: (e) => { if (!e.target.closest("a")) location.hash = href; } },
        h("td", null,
          h("a", { class: "row-link", href }, U.fmtDate(s.started_at)),
          h("span", { class: "muted num" }, ` · #${s.id}`),
          s.id === recordingId ? h("span", { class: "tag tag--rec", style: { marginLeft: "0.5rem" } }, "Recording") : null),
        h("td", null, h("span", { class: "classbadge" }, U.carClass(s.car_class)), ` ${s.car_pi ?? ""} · ${s.drivetrain ?? ""}`, h("span", { class: "muted num" }, ` · car #${s.car_ordinal ?? "?"}`)),
        h("td", { class: "num" }, U.trackLabel(s.track_ordinal)),
        h("td", { class: "r num" }, String(s.lap_count ?? 0)),
        h("td", { class: "r num strong" }, U.fmtLapTime(s.best_lap)),
        h("td", { class: "note-cell" }, s.note || h("span", { class: "muted" }, "–")));
      return tr;
    }));
    body.append(h("table", { class: "table table--sticky sessions-table" }, thead, tbody));
  }

  let lastActive = !!store.get("status")?.recording?.active;
  load();
  const offLap = store.on("lapCompleted", load);
  const offStatus = store.on("status", (st) => {
    const active = !!st?.recording?.active;
    if (active !== lastActive) {
      lastActive = active;
      load();
    }
  });
  return () => {
    alive = false;
    offLap();
    offStatus();
  };
}

export function skeletonTable(rows = 5) {
  return h("div", { class: "skeleton-table", "aria-hidden": "true" },
    Array.from({ length: rows }, () => h("span", { class: "skeleton", style: { height: "2.75rem", marginBottom: "0.5rem" } })));
}
