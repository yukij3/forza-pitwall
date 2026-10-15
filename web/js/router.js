// Hash routing so a plain static server works: #/live, #/sessions,
// #/sessions/:id, #/laps/:id, #/baseline, #/settings. Query after "?" in the hash.

const ROUTES = [
  { name: "live", pattern: /^\/live\/?$/ },
  { name: "sessions", pattern: /^\/sessions\/?$/ },
  { name: "session", pattern: /^\/sessions\/([^/]+)\/?$/, keys: ["id"] },
  { name: "lap", pattern: /^\/laps\/([^/]+)\/?$/, keys: ["id"] },
  { name: "baseline", pattern: /^\/baseline\/?$/ },
  { name: "settings", pattern: /^\/settings\/?$/ },
];

export function parseHash(hash = location.hash) {
  const raw = hash.replace(/^#/, "") || "/live";
  const [path, qs = ""] = raw.split("?");
  const query = Object.fromEntries(new URLSearchParams(qs));
  for (const r of ROUTES) {
    const m = path.match(r.pattern);
    if (m) {
      const params = {};
      (r.keys || []).forEach((k, i) => (params[k] = decodeURIComponent(m[i + 1])));
      return { name: r.name, params, query, path };
    }
  }
  return { name: "notfound", params: {}, query, path };
}

/** Top-level section for the rail highlight. */
export function sectionOf(route) {
  if (route.name === "session" || route.name === "lap") return "sessions";
  return route.name;
}

export function href(path, query) {
  const qs = query ? new URLSearchParams(query).toString() : "";
  return `#${path}${qs ? `?${qs}` : ""}`;
}

export function onRoute(fn) {
  const handler = () => fn(parseHash());
  window.addEventListener("hashchange", handler);
  handler();
  return () => window.removeEventListener("hashchange", handler);
}
