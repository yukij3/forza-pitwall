// Authored icon set: 24px grid, 1.75 stroke, square caps. One weight everywhere.
import { s } from "./dom.js";

const PATHS = {
  live: ["M3 12h4l2.5-6 5 12 2.5-6H21"],
  sessions: ["M4 5h16", "M4 10h16", "M4 15h10", "M4 20h7", "M18 15v6", "M15 18h6"],
  baseline: ["M5 4v7", "M5 15v5", "M12 4v3", "M12 11v9", "M19 4v10", "M19 18v2", "M3 13h4", "M10 9h4", "M17 16h4"],
  settings: ["M12 3v3", "M12 18v3", "M3 12h3", "M18 12h3", "M5.6 5.6l2.1 2.1", "M16.3 16.3l2.1 2.1", "M5.6 18.4l2.1-2.1", "M16.3 7.7l2.1-2.1", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"],
  copy: ["M9 9h11v11H9z", "M5 15H4V4h11v1"],
  check: ["M4 12.5l5 5L20 6.5"],
  chevronRight: ["M9 5l7 7-7 7"],
  chevronLeft: ["M15 5l-7 7 7 7"],
  sort: ["M8 4v16", "M4 16l4 4 4-4", "M16 20V4", "M12 8l4-4 4 4"],
  sortAsc: ["M12 20V4", "M6 10l6-6 6 6"],
  sortDesc: ["M12 4v16", "M6 14l6 6 6-6"],
  reset: ["M4 4v6h6", "M4.5 10A8 8 0 1 1 6 16.5"],
  arrowRight: ["M4 12h16", "M14 6l6 6-6 6"],
  trash: ["M4 7h16", "M9 7V4h6v3", "M6 7l1 13h10l1-13"],
  plus: ["M12 4v16", "M4 12h16"],
  overlay: ["M3 17l5-6 4 4 4-7 5 6", "M3 13l5-3 4 2 4-5 5 3"],
  external: ["M14 4h6v6", "M20 4l-9 9", "M18 14v6H4V6h6"],
  wifiOff: ["M3 3l18 18", "M8.5 16.5a5 5 0 0 1 7 0", "M5 13a10 10 0 0 1 5-2.6", "M14 10.4A10 10 0 0 1 19 13", "M12 20h.01"],
};

export function icon(name, cls = "icon") {
  const paths = PATHS[name] || [];
  return s(
    "svg",
    { class: cls, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "1.75", "stroke-linecap": "square", "stroke-linejoin": "miter", "aria-hidden": "true", focusable: "false" },
    paths.map((d) => s("path", { d }))
  );
}

/** Pitwall mark: a flag on a pole, the marshal's signal. */
export function brandMark(cls = "rail__mark") {
  return s(
    "svg",
    { class: cls, viewBox: "0 0 36 24", "aria-hidden": "true", focusable: "false" },
    s("rect", { x: "2", y: "1", width: "3", height: "22", fill: "currentColor" }),
    s("rect", { x: "5", y: "1", width: "29", height: "15", fill: "currentColor" }),
    s("rect", { x: "8", y: "4", width: "6", height: "4.5", fill: "var(--orange)" }),
    s("rect", { x: "20", y: "4", width: "6", height: "4.5", fill: "var(--orange)" }),
    s("rect", { x: "14", y: "8.5", width: "6", height: "4.5", fill: "var(--orange)" }),
    s("rect", { x: "26", y: "8.5", width: "5", height: "4.5", fill: "var(--orange)" })
  );
}
