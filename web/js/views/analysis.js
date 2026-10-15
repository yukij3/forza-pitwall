// Read-only rendering of SessionAnalysis / LapAnalysis: the next change in
// game wording, alternatives, findings with evidence, and Data Out limits.

import { h, flag, gameText } from "../dom.js";
import * as U from "../units.js";

function confidence(c) {
  if (c === null || c === undefined) return null;
  const on = Math.round(c * 5);
  return h("span", { class: "confidence", title: "Confidence" },
    h("span", { class: "segments", "aria-hidden": "true" }, [0, 1, 2, 3, 4].map((i) => h("i", { class: i < on ? "on" : "" }))),
    h("span", { class: "num" }, h("span", { class: "sr-only" }, "Confidence "), `${Math.round(c * 100)}%`));
}

const reasonLine = (text) => (text ? U.minus(String(text).trim().replace(/\.+$/, "")) : "");

function nextChange(rec) {
  return h("section", { class: "next", "aria-labelledby": "next-title" },
    h("h2", { id: "next-title", class: "next__head" }, flag("meatball", "flag--md"), h("span", null, "Next change")),
    h("p", { class: "next__rec" }, gameText(rec.text)),
    h("div", { class: "next__foot" },
      rec.reason ? h("span", { class: "next__reason num", title: rec.detail ?? null }, reasonLine(rec.reason)) : null,
      confidence(rec.confidence)));
}

function findingsList(findings, onWhere) {
  if (!findings?.length) return h("p", { class: "muted" }, "No findings");
  const sorted = [...findings].sort((a, b) => (b.severity ?? 0) - (a.severity ?? 0));
  return h("ol", { class: "findings" }, sorted.map((f) => {
    const sev = f.severity ?? 0;
    const on = Math.max(1, Math.round(sev * 5));
    return h("li", { class: "finding" },
      h("div", { class: "finding__sev", title: `Severity ${Math.round(sev * 100)}%` },
        h("span", { class: "segments", "aria-hidden": "true" }, [0, 1, 2, 3, 4].map((i) => h("i", { class: i < on ? "on" : "" }))),
        h("span", { class: "num" }, h("span", { class: "sr-only" }, "Severity "), `${Math.round(sev * 100)}%`)),
      h("div", { class: "finding__body" },
        h("h3", { class: "finding__title" }, f.title),
        f.evidence ? h("p", { class: "finding__evidence num", title: f.detail ?? null }, reasonLine(f.evidence)) : null,
        f.where?.length
          ? h("p", { class: "finding__where" }, f.where.map((w) => {
            const label = `${w.corner !== undefined && w.corner !== null ? `T${w.corner}` : "At"} · ${U.fmtDistance(w.distance)}`;
            return onWhere
              ? h("button", { class: "chip", type: "button", onclick: () => onWhere(w.distance) }, label)
              : h("span", { class: "chip" }, label);
          }))
          : null));
  }));
}

function limitsList(limits) {
  if (!limits?.length) return null;
  return h("details", { class: "limits" },
    h("summary", null, "Limits ", h("span", { class: "muted num" }, `(${limits.length})`)),
    h("ul", null, limits.map((l) => h("li", null, gameText(reasonLine(l))))));
}

export function renderSessionAnalysis(an, { onWhere } = {}) {
  const parts = [];
  const n = an.laps_analyzed ?? 0;
  if (an.next_change) {
    parts.push(nextChange(an.next_change));
  } else {
    parts.push(h("section", { class: "next next--none" },
      h("h2", { class: "next__head" }, flag("none", "flag--md"), h("span", null, "No change")),
      h("p", { class: "next__reason num" }, n < 3 ? `${n}/3 valid flying laps` : "Nothing off target")));
  }
  if (an.alternatives?.length) {
    parts.push(h("section", { class: "alts", "aria-labelledby": "alts-title" },
      h("h2", { id: "alts-title", class: "block-title" }, "Alternatives"),
      h("ul", null, an.alternatives.map((r) => h("li", { class: "alt" },
        h("p", { class: "alt__rec" }, gameText(r.text)),
        h("div", { class: "alt__foot" },
          r.reason ? h("span", { class: "alt__reason num", title: r.detail ?? null }, reasonLine(r.reason)) : null,
          confidence(r.confidence)))))));
  }
  parts.push(h("section", { "aria-labelledby": "findings-title" },
    h("h2", { id: "findings-title", class: "block-title" }, "Findings ",
      h("span", { class: "muted num", title: "Valid flying laps" }, `${n} ${n === 1 ? "lap" : "laps"}`)),
    findingsList(an.findings, onWhere)));
  const lim = limitsList(an.limits);
  if (lim) parts.push(lim);
  return h("div", { class: "analysis" }, parts);
}

export function renderLapFindings(la, onWhere) {
  const findings = la?.findings || [];
  return h("section", { class: "analysis", "aria-labelledby": "lapf-title" },
    h("h2", { id: "lapf-title", class: "block-title" }, "Findings",
      la && la.valid_for_findings === false
        ? h("span", { class: "muted", title: "Only valid flying laps count" }, " · not counted")
        : null),
    findingsList(findings, onWhere));
}
