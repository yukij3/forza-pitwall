// Unit conversion and formatting. The API speaks canonical units
// (m/s, °C, m, s, rad, 0..1 pedals, -1..1 steer); this module turns them into
// what the player chose in Settings.

const MINUS = "−";

let units = { speed: "kmh", temperature: "C", pressure: "psi" };

export function setUnits(next) {
  if (next) units = { ...units, ...next };
}
export function getUnits() {
  return units;
}

// --- speed
export function speedValue(ms) {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return null;
  return units.speed === "mph" ? ms * 2.236936 : ms * 3.6;
}
export function speedUnit() {
  return units.speed === "mph" ? "mph" : "km/h";
}
export function fmtSpeed(ms, withUnit = false) {
  const v = speedValue(ms);
  if (v === null) return "–";
  const n = Math.round(v).toString();
  return withUnit ? `${n} ${speedUnit()}` : n;
}

// --- temperature
export function tempValue(c) {
  if (c === null || c === undefined || Number.isNaN(c)) return null;
  return units.temperature === "F" ? c * 1.8 + 32 : c;
}
export function tempDelta(c) {
  return units.temperature === "F" ? c * 1.8 : c;
}
export function tempUnit() {
  return units.temperature === "F" ? "°F" : "°C";
}
export function fmtTemp(c, withUnit = false) {
  const v = tempValue(c);
  if (v === null) return "–";
  return `${Math.round(v)}${withUnit ? ` ${tempUnit()}` : "°"}`;
}

/** Rule-of-thumb operating window. Not a game value: Data Out has one temperature per tyre. */
export const TIRE_WINDOW_C = [80, 100];
export const TIRE_SCALE_C = [40, 130];

export function tireState(c) {
  if (c === null || c === undefined) return "unknown";
  if (c < TIRE_WINDOW_C[0]) return "cold";
  if (c > TIRE_WINDOW_C[1]) return "hot";
  return "ok";
}

// --- pressure
export function pressureUnit() {
  return units.pressure === "bar" ? "bar" : "psi";
}
export function convertPressure(value, from, to) {
  if (from === to) return value;
  if (from === "psi" && to === "bar") return value * 0.0689476;
  if (from === "bar" && to === "psi") return value / 0.0689476;
  return value;
}

// --- numbers
export function signed(n, digits = 0, unit = "") {
  if (n === null || n === undefined || Number.isNaN(n)) return "–";
  const abs = Math.abs(n).toFixed(digits);
  if (Number(abs) === 0) return `${(0).toFixed(digits)}${unit}`;
  return `${n < 0 ? MINUS : "+"}${abs}${unit}`;
}

/** Typographic minus for negative numbers only; hyphens in words stay. */
export function minus(str) {
  return String(str).replace(/(^|[\s(\[…,])-(?=\d|\.\d)/g, `$1${MINUS}`);
}

export function pct(x, digits = 0) {
  if (x === null || x === undefined) return "–";
  return `${(x * 100).toFixed(digits)}%`;
}

// --- time
export function fmtLapTime(s) {
  if (s === null || s === undefined || !(s > 0) || !Number.isFinite(s)) return "–:––.–––";
  const m = Math.floor(s / 60);
  const rest = s - m * 60;
  return `${m}:${rest.toFixed(3).padStart(6, "0")}`;
}

export function fmtDelta(s, digits = 3) {
  if (s === null || s === undefined || Number.isNaN(s)) return "–";
  return signed(s, digits);
}

export function fmtDuration(totalSeconds) {
  if (totalSeconds === null || totalSeconds === undefined || totalSeconds < 0) return "–";
  const t = Math.floor(totalSeconds);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = t % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(sec).padStart(2, "0")}`;
}

export function fmtDistance(m) {
  if (m === null || m === undefined) return "–";
  if (units.speed === "mph") return `${(m / 1609.344).toFixed(2)} mi`;
  return m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`;
}

const DATE_FMT = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const DAY_FMT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const TIME_FMT = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });

export function fmtDate(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "–" : DATE_FMT.format(d);
}
export function fmtDay(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "–" : DAY_FMT.format(d);
}
export function fmtClock(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "–" : TIME_FMT.format(d);
}

// --- car
// Data Out car class index. Mapping D..X assumed from the published Forza docs;
// verify against the game and adjust here if it differs.
const CLASSES = ["D", "C", "B", "A", "S", "R", "P", "X"];
export function carClass(n) {
  if (n === null || n === undefined) return "?";
  return CLASSES[n] ?? `#${n}`;
}
export function carLabel(car) {
  if (!car) return "No car yet";
  return `${carClass(car.class)} ${car.pi}`;
}

export function trackLabel(ordinal) {
  return ordinal === null || ordinal === undefined ? "Unknown track" : `Track #${ordinal}`;
}
