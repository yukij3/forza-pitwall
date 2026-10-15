// Tiny DOM helpers. No framework: views build elements with h() and patch
// the few live values in place so nothing reflows while the player drives.

const SVG_NS = "http://www.w3.org/2000/svg";

function applyAttrs(el, attrs, isSvg) {
  if (!attrs) return;
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") {
      el.setAttribute("class", Array.isArray(value) ? value.filter(Boolean).join(" ") : value);
    } else if (key === "style" && typeof value === "object") {
      for (const [prop, v] of Object.entries(value)) {
        if (prop.startsWith("--")) el.style.setProperty(prop, v);
        else el.style[prop] = v;
      }
    } else if (key === "dataset") {
      Object.assign(el.dataset, value);
    } else if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "text") {
      el.textContent = value;
    } else if (key === "html") {
      el.innerHTML = value;
    } else if (!isSvg && (key === "value" || key === "checked" || key === "disabled" || key === "selected")) {
      el[key] = value;
    } else {
      el.setAttribute(key, value === true ? "" : String(value));
    }
  }
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs && (attrs instanceof Node || typeof attrs !== "object" || Array.isArray(attrs))) {
    children.unshift(attrs);
    attrs = null;
  }
  applyAttrs(el, attrs, false);
  append(el, children);
  return el;
}

export function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  applyAttrs(el, attrs, true);
  append(el, children);
  return el;
}

/** Empty an element. Returns { append } that skips null/false children, like h(). */
export function clear(el) {
  while (el.firstChild) el.firstChild.remove();
  return {
    append: (...children) => { append(el, children); return el; },
  };
}

export function setText(el, text) {
  const next = text ?? "";
  if (el.textContent !== next) el.textContent = next;
}

export function setAttr(el, name, value) {
  if (value === null || value === undefined || value === false) {
    if (el.hasAttribute(name)) el.removeAttribute(name);
  } else {
    const v = value === true ? "" : String(value);
    if (el.getAttribute(name) !== v) el.setAttribute(name, v);
  }
}

/** Re-trigger a one-shot CSS animation class. */
export function replay(el, cls) {
  el.classList.remove(cls);
  void el.offsetWidth;
  el.classList.add(cls);
}

/** Flag swatch: always paired with a word by the caller. */
export function flag(kind, extraClass) {
  return h("span", { class: ["flag", `flag--${kind}`, extraClass], "aria-hidden": "true" });
}

export function signal(kind, word, extra) {
  return h("span", { class: ["signal", extra] }, flag(kind), h("span", null, word));
}

/** Split game wording on the arrow so it can fall back to a symbol face. */
export function gameText(text) {
  if (!text) return document.createTextNode("");
  const parts = String(text).split("→");
  const frag = document.createDocumentFragment();
  parts.forEach((part, i) => {
    if (i > 0) frag.append(h("span", { class: "arrow" }, "→"));
    frag.append(part);
  });
  return frag;
}

export function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}
