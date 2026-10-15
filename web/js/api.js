// REST client for the Pitwall API. Errors arrive as
// {"error": {"code", "message"}} with a 4xx/5xx status; network failures
// surface as ApiError with code "network".

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function describeError(err) {
  if (err instanceof ApiError) {
    if (err.code === "network") return "Server unreachable";
    return err.message || `Request failed (${err.status}).`;
  }
  return err?.message || "Something went wrong.";
}

export function createApi(fetchImpl, base = "") {
  const doFetch = fetchImpl || ((...args) => window.fetch(...args));

  async function request(method, path, body) {
    const init = { method, headers: { Accept: "application/json" } };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await doFetch(`${base}/api${path}`, init);
    } catch (e) {
      throw new ApiError(0, "network", e?.message || "Network error");
    }
    if (res.status === 204) return null;
    let data = null;
    const text = await res.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        if (!res.ok) throw new ApiError(res.status, "bad_response", `Server returned ${res.status}.`);
        throw new ApiError(res.status, "bad_response", "Response isn't JSON");
      }
    }
    if (!res.ok) {
      const err = data && data.error;
      throw new ApiError(res.status, err?.code || `http_${res.status}`, err?.message || `Request failed (${res.status}).`);
    }
    return data;
  }

  const get = (p) => request("GET", p);
  const enc = encodeURIComponent;

  return {
    status: () => get("/status"),
    startRecording: (note) => request("POST", "/recording/start", note ? { note } : {}),
    stopRecording: () => request("POST", "/recording/stop", {}),

    sessions: () => get("/sessions"),
    session: (id) => get(`/sessions/${enc(id)}`),
    patchSession: (id, patch) => request("PATCH", `/sessions/${enc(id)}`, patch),
    deleteSession: (id) => request("DELETE", `/sessions/${enc(id)}`),
    sessionAnalysis: (id) => get(`/sessions/${enc(id)}/analysis`),

    lap: (id) => get(`/laps/${enc(id)}`),
    lapTrace: (id, hz = 20) => get(`/laps/${enc(id)}/trace?hz=${enc(hz)}`),
    lapAnalysis: (id) => get(`/laps/${enc(id)}/analysis`),

    liveAnalysis: () => get("/live-analysis"),
    resetLiveAnalysis: () => request("POST", "/live-analysis/reset", {}),

    tuneSchema: () => get("/tune-schema"),

    baseline: () => get("/baseline"),
    baselineCategories: () => get("/baseline/categories"),
    baselineFor: (categoryId) => get(`/baseline/${enc(categoryId)}`),

    settings: () => get("/settings"),
    saveSettings: (settings) => request("PUT", "/settings", settings),
  };
}
