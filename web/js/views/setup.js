// "What to enter in the game" hint: exactly the Data Out rows to set.

import { h, flag } from "../dom.js";
import { icon } from "../icons.js";

function guessHost() {
  const host = location.hostname;
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(host) && host !== "127.0.0.1") return host;
  return null;
}

async function copy(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = h("textarea", { style: { position: "fixed", opacity: "0" } }, text);
    document.body.append(ta);
    ta.select();
    try { document.execCommand("copy"); } catch { /* clipboard blocked */ }
    ta.remove();
  }
  const label = btn.querySelector("span");
  const prev = label.textContent;
  label.textContent = "Copied";
  btn.classList.add("is-done");
  setTimeout(() => {
    label.textContent = prev;
    btn.classList.remove("is-done");
  }, 1600);
}

export function dataOutRows(status) {
  const r = status?.receiver || {};
  const host = r.public_host || guessHost();
  const port = r.udp_port ?? 5300;
  const copyBtn = (value, what) =>
    h("button", { class: "btn btn--sm btn--quiet copy", type: "button", "aria-label": `Copy ${what}`, onclick: (e) => copy(String(value), e.currentTarget) },
      icon("copy"), h("span", null, "Copy"));

  const rows = [
    ["Data Out", h("b", null, "On")],
    ["Data Out IP Address", host
      ? h("span", { class: "dataout__value" }, h("b", { class: "num" }, host), copyBtn(host, "IP address"))
      : h("span", { class: "dataout__value", title: "Set PITWALL_PUBLIC_HOST to show it here" }, h("b", null, "LAN IP of this server"))],
    ["Data Out IP Port", h("span", { class: "dataout__value" }, h("b", { class: "num" }, String(port)), copyBtn(port, "port"))],
    ["Data Out Packet Format", h("b", null, "Car Dash")],
  ];
  return h("dl", { class: "dataout" }, rows.map(([k, v]) => h("div", { class: "dataout__row" }, h("dt", null, k), h("dd", null, v))));
}

export function setupPanel(status, feed) {
  const r = status?.receiver || {};
  const listening = r.listening !== false;
  const port = r.udp_port ?? 5300;
  const title = listening ? "No telemetry" : "Receiver not listening";
  const facts = [listening ? `UDP ${port}` : `UDP ${port} unavailable`];
  if (feed === "waiting" && r.last_packet_age_s) facts.push(`last packet ${Math.round(r.last_packet_age_s)} s ago`);
  return h("section", { class: "setup", "aria-labelledby": "setup-title" },
    h("div", { class: "setup__head" },
      flag(listening ? "yellow" : "red", "flag--lg"),
      h("h1", { id: "setup-title", class: "setup__title" }, title),
      h("span", { class: "setup__facts num" }, facts.join(" · "))),
    listening ? h("div", { class: "setup__body" },
      h("p", { class: "setup__path" }, "Settings", h("span", { class: "arrow" }, "→"), "Gameplay & HUD", h("span", { class: "arrow" }, "→"), "Data Out"),
      dataOutRows(status)) : null
  );
}
