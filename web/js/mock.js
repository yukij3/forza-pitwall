// Mock backend for ?mock=1. Simulates the REST API and /ws/live in the
// browser so the UI can be developed and demoed without the game or server.
// Every number here is synthetic; the UI labels mock mode as a demo.

import { Driver, TRACK, defaultModel, simulateLap, rng } from "./mock-sim.js";
import { CATEGORIES, baselineFor } from "./mock-baselines.js";

const MINUS = "−";
const HOUR = 3600 * 1000;
const DAY = 24 * HOUR;

// Mirrors pitwall/tune/settings.py: used to word recommendations in game-menu terms.
const ALL = ["FWD", "RWD", "AWD"];
const SCHEMA = [
  ["tires.pressure_front", "Tires", "Tire Pressure", "Front", "psi", "bar"],
  ["tires.pressure_rear", "Tires", "Tire Pressure", "Rear", "psi", "bar"],
  ["gearing.final_drive", "Gearing", "Final Drive", null, "", ""],
  ["alignment.camber_front", "Alignment", "Camber", "Front", "°", "°"],
  ["alignment.camber_rear", "Alignment", "Camber", "Rear", "°", "°"],
  ["alignment.toe_front", "Alignment", "Toe", "Front", "°", "°"],
  ["alignment.toe_rear", "Alignment", "Toe", "Rear", "°", "°"],
  ["alignment.caster", "Alignment", "Caster", "Front", "°", "°"],
  ["arb.front", "Anti-roll Bars", "Anti-roll Bars", "Front", "", ""],
  ["arb.rear", "Anti-roll Bars", "Anti-roll Bars", "Rear", "", ""],
  ["springs.front", "Springs", "Springs", "Front", "lb/in", "kgf/mm"],
  ["springs.rear", "Springs", "Springs", "Rear", "lb/in", "kgf/mm"],
  ["springs.ride_height_front", "Springs", "Ride Height", "Front", "in", "cm"],
  ["springs.ride_height_rear", "Springs", "Ride Height", "Rear", "in", "cm"],
  ["damping.rebound_front", "Damping", "Rebound Stiffness", "Front", "", ""],
  ["damping.rebound_rear", "Damping", "Rebound Stiffness", "Rear", "", ""],
  ["damping.bump_front", "Damping", "Bump Stiffness", "Front", "", ""],
  ["damping.bump_rear", "Damping", "Bump Stiffness", "Rear", "", ""],
  ["geometry.roll_center_front", "Geometry", "Roll Center Height Offset", "Front", "in", "cm"],
  ["geometry.roll_center_rear", "Geometry", "Roll Center Height Offset", "Rear", "in", "cm"],
  ["geometry.anti_front", "Geometry", "Anti-dive", "Front", "%", "%"],
  ["geometry.anti_rear", "Geometry", "Anti-squat", "Rear", "%", "%"],
  ["aero.front", "Aero", "Downforce", "Front", "lb", "kgf"],
  ["aero.rear", "Aero", "Downforce", "Rear", "lb", "kgf"],
  ["brake.balance", "Brake", "Braking Balance", null, "% front", "% front"],
  ["brake.pressure", "Brake", "Braking Pressure", null, "%", "%"],
  ["diff.accel_front", "Differential", "Acceleration", "Front", "%", "%", ["FWD", "AWD"]],
  ["diff.decel_front", "Differential", "Deceleration", "Front", "%", "%", ["FWD", "AWD"]],
  ["diff.accel_rear", "Differential", "Acceleration", "Rear", "%", "%", ["RWD", "AWD"]],
  ["diff.decel_rear", "Differential", "Deceleration", "Rear", "%", "%", ["RWD", "AWD"]],
  ["diff.center_balance", "Differential", "Center Balance", null, "% rear", "% rear", ["AWD"]],
].map(([key, section, label, axle, unit_imperial, unit_metric, drivetrains = ALL]) => ({ key, section, label, axle, unit_imperial, unit_metric, drivetrains }));
const BY_KEY = Object.fromEntries(SCHEMA.map((s) => [s.key, s]));

const CAR = { ordinal: 2254, class: 6, pi: 900, drivetrain: "RWD", name: "2014 Mazda #70 SpeedSource Lola B12/80", division: "Forza P2" };
const TRACK_ORDINAL = 860;

// How a setup change nudges the demo car (per unit of change). After "Reset board"
// the mock assumes the player made the focus change in game.
const EFFECTS = {
  "arb.front": { midSlowU: 0.05, midFastU: 0.02 },
  "arb.rear": { midSlowU: -0.04, exitO: 0.02, wheelspin: 0.06 },
  "aero.front": { midFastU: -0.004 },
  "aero.rear": { midFastU: 0.003 },
  "diff.accel_rear": { exitO: 0.006, wheelspin: 0.02 },
  "diff.decel_rear": { rearStep: -0.01 },
  "brake.pressure": { lockFront: 0.03 },
  "brake.balance": { lockFront: 0.08, lockRear: -0.03 },
  "springs.ride_height_front": { bottomFront: -0.6 },
  "springs.ride_height_rear": { bottomRear: -0.6 },
  "gearing.final_drive": { limiter: 3 },
  "tires.pressure_rear": { rearHot: 2 },
  "springs.rear": { exitO: 0.0006, wheelspin: 0.002 },
};

const r2 = (x, d = 2) => Number(x.toFixed(d));
const iso = (ms) => new Date(ms).toISOString();

export function createMockBackend() {
  const t0 = Date.now();
  const scenarioKey = "pitwall.mock.scenario";
  let scenario = sessionStorage.getItem(scenarioKey) || "driving";

  const settings = { units: { speed: "kmh", temperature: "C", pressure: "psi" }, auto_record: false };

  // ------------------------------------------------------------- sessions
  const sessions = [];
  const laps = new Map();
  let nextSessionId = 11;
  let nextLapId = 101;

  function seedSession(pace, startedMs, plan, note) {
    const s = {
      id: nextSessionId++, started_at: iso(startedMs), stopped_at: null,
      car_ordinal: CAR.ordinal, car_pi: CAR.pi, car_class: CAR.class, drivetrain: CAR.drivetrain,
      track_ordinal: TRACK_ORDINAL, note, lapIds: [],
    };
    let tMs = startedMs;
    plan.forEach((kind, i) => {
      const seed = s.id * 100 + i;
      const partial = kind === "partial" ? 0.55 : 1;
      const res = simulateLap({ seed, model: defaultModel(), kind: kind === "partial" ? "flying" : kind, pace, partial });
      const invalid = kind === "invalid";
      const lap = {
        id: nextLapId++, session_id: s.id, number: i + 1,
        lap_time: kind === "partial" ? null : r2(res.lapTime, 3),
        kind: kind === "invalid" ? "flying" : kind,
        valid: !(invalid || kind === "partial"),
        invalid_reason: invalid ? "Rewind detected" : kind === "partial" ? "Recording stopped mid-lap" : null,
        frame_count: res.frames * 3, started_at: iso(tMs),
        _seed: seed, _pace: pace, _kindSim: kind === "partial" || kind === "invalid" ? "flying" : kind, _partial: partial,
        _summary: { tireAvg: res.tireAvg, events: res.events, wearDelta: res.wearDelta },
      };
      tMs += res.lapTime * 1000;
      laps.set(lap.id, lap);
      s.lapIds.push(lap.id);
    });
    s.stopped_at = iso(tMs + 20000);
    sessions.unshift(s);
    return s;
  }
  seedSession(0.982, t0 - 3 * DAY, ["out", "flying", "flying", "flying", "flying", "in"], "First run on the baseline.");
  seedSession(0.987, t0 - 2 * DAY, ["out", "flying", "invalid", "flying", "flying"], "");
  seedSession(0.987, t0 - 2 * DAY + 4 * HOUR, ["out", "flying", "flying", "flying", "flying", "flying", "in"], "Long run, tyres went off at the end.");
  seedSession(0.991, t0 - 5 * HOUR, ["out", "flying", "flying", "flying", "flying", "partial"], "");

  const sessionLaps = (s) => s.lapIds.map((id) => laps.get(id)).filter(Boolean);
  function publicLap(l) {
    const { _seed, _pace, _kindSim, _partial, _summary, _trace, ...rest } = l;
    return rest;
  }
  function publicSession(s) {
    const ls = sessionLaps(s);
    const valid = ls.filter((l) => l.valid && l.kind === "flying" && l.lap_time);
    const best = valid.length ? Math.min(...valid.map((l) => l.lap_time)) : null;
    const { lapIds, ...rest } = s;
    return { ...rest, lap_count: ls.length, best_lap: best };
  }

  function lapTrace(l) {
    if (l._trace) return l._trace;
    const res = simulateLap({ seed: l._seed, model: defaultModel(), kind: l._kindSim, pace: l._pace, partial: l._partial });
    return res.trace;
  }

  // --------------------------------------------------------- recommendations
  function stepText(step, unit) {
    if (step < 1 && !Number.isInteger(step)) step = step.toFixed(2);
    if (!unit) return `${step}`;
    if (unit.startsWith("%")) return `${step}%`;
    if (unit === "°") return `${step}°`;
    return `${step} ${unit}`;
  }
  function rec(setting, direction, step, { id, finding_id = null, reason, confidence, priority = 1 }) {
    const s = BY_KEY[setting];
    const metric = false; // v1 has no tune, so the game's unit system is unknown: imperial wording
    let unit = metric ? s.unit_metric : s.unit_imperial;
    if (unit === "% front" || unit === "% rear") unit = "%";
    let stepVal = step;
    if (s.unit_imperial === "psi" && settings.units.pressure === "bar" && !metric) {
      unit = "bar";
      stepVal = r2(step * 0.0689476, 2);
    }
    const sign = direction === "decrease" ? MINUS : "+";
    const where = s.label === s.section ? `${s.section} → ${s.axle}` : `${s.section} → ${s.label}${s.axle ? ` (${s.axle})` : ""}`;
    return {
      id: id || `${setting}-${direction}`, finding_id, setting, section: s.section, label: s.label, axle: s.axle,
      direction, step: stepVal, step_unit: unit, suggested_value: null,
      text: `${where}: ${sign}${stepText(stepVal, unit)}`, reason, confidence, priority,
    };
  }

  // ------------------------------------------------------- live analyzer
  const model = defaultModel();
  const SAMPLERS = {
    every: (e) => e.type === "corner",
    slow: (e) => e.type === "corner" && e.corner.slow,
    fast: (e) => e.type === "corner" && !e.corner.slow,
    lap: (e) => e.type === "lap",
  };
  const tempUnit = () => (settings.units.temperature === "F" ? "°F" : "°C");
  const tconv = (d) => (settings.units.temperature === "F" ? d * 1.8 : d);
  const balText = (v) => (v > 0.03 ? `Understeer ${Math.abs(v).toFixed(2)}` : v < -0.03 ? `Oversteer ${Math.abs(v).toFixed(2)}` : `Neutral ${Math.abs(v).toFixed(2)}`);
  const BAL_TARGET = [-0.05, 0.1];
  const balTargetText = `${MINUS}0.05 … +0.10`;

  const ITEMS = [
    { id: "entry_balance", group: "Balance", title: "Corner entry", sample: "every", needs: 5, target: BAL_TARGET, ttext: () => balTargetText, truth: () => model.entryU, noise: 0.05, vtext: balText,
      per: "entries", fix: (v) => (v > 0 ? ["brake.balance", "decrease", 2, "Understeer"] : ["diff.decel_rear", "increase", 5, "Oversteer"]) },
    { id: "mid_balance_low", group: "Balance", title: "Mid-corner, slow corners", sample: "slow", needs: 4, target: BAL_TARGET, ttext: () => balTargetText, truth: () => model.midSlowU, noise: 0.05, vtext: balText,
      per: "slow apexes", fix: (v) => (v > 0 ? ["arb.front", "decrease", 2, "Understeer"] : ["arb.rear", "decrease", 2, "Oversteer"]) },
    { id: "mid_balance_high", group: "Balance", title: "Mid-corner, fast corners", sample: "fast", needs: 4, target: BAL_TARGET, ttext: () => balTargetText, truth: () => model.midFastU, noise: 0.04, vtext: balText,
      per: "fast apexes", fix: (v) => (v > 0 ? ["aero.front", "increase", 10, "Understeer"] : ["aero.rear", "increase", 10, "Oversteer"]) },
    { id: "exit_balance", group: "Balance", title: "Corner exit", sample: "every", needs: 5, target: BAL_TARGET, ttext: () => balTargetText,
      truth: (t) => -model.exitO - Math.min(0.17, Math.max(0, (t - 35) * 0.0011)), noise: 0.05, vtext: balText,
      per: "exits", fix: (v) => (v < 0 ? ["diff.accel_rear", "decrease", 5, "Oversteer"] : ["diff.accel_rear", "increase", 5, "Understeer"]) },
    { id: "exit_wheelspin", group: "Traction", title: "Wheelspin on exit", sample: "slow", needs: 5, target: [null, 0.5], ttext: () => "≤ 0.5 s per lap",
      truth: (t) => model.wheelspin + Math.min(0.3, Math.max(0, (t - 60) * 0.0015)), noise: 0.12, vtext: (v) => `${Math.max(0, v).toFixed(1)} s per lap`,
      per: "slow exits", fix: () => ["arb.rear", "decrease", 1, "Wheelspin"] },
    { id: "front_lockups", group: "Braking", title: "Front lock-ups", sample: "every", needs: 6, target: [null, 0.5], ttext: () => "≤ 0.5 per lap",
      truth: () => model.lockFront * 1.4, noise: 0.15, vtext: (v) => `${Math.max(0, v).toFixed(1)} per lap`,
      per: "stops", fix: () => ["brake.pressure", "decrease", 5, "Front lock"] },
    { id: "rear_lockups", group: "Braking", title: "Rear lock-ups", sample: "every", needs: 14, target: [null, 0.5], ttext: () => "≤ 0.5 per lap",
      truth: () => model.lockRear * 2, noise: 0.08, vtext: (v) => `${Math.max(0, v).toFixed(1)} per lap`,
      per: "stops", fix: () => ["brake.balance", "increase", 2, "Rear lock"] },
    { id: "braking_stability", group: "Braking", title: "Stability under braking", sample: "every", needs: 6, target: [null, 0.5], ttext: () => "rear slip ≤ 0.50",
      truth: () => model.rearStep, noise: 0.06, vtext: (v) => `Rear slip ${Math.max(0, v).toFixed(2)}`,
      per: "stops", fix: () => ["diff.decel_rear", "increase", 5, "Rear slip"] },
    { id: "bottoming_front", group: "Suspension", title: "Bottoming, front", sample: "every", needs: 8, target: [null, 0.5], ttext: () => "≤ 0.5 per lap",
      truth: () => model.bottomFront * 4, noise: 0.15, vtext: (v) => `${Math.max(0, v).toFixed(1)} per lap`,
      per: "corners", fix: () => ["springs.ride_height_front", "increase", 0.2, "Bottoming"] },
    { id: "bottoming_rear", group: "Suspension", title: "Bottoming, rear", sample: "every", needs: 10, target: [null, 0.5], ttext: () => "≤ 0.5 per lap",
      truth: () => model.bottomRear * 4, noise: 0.1, vtext: (v) => `${Math.max(0, v).toFixed(1)} per lap`,
      per: "corners", fix: () => ["springs.ride_height_rear", "increase", 0.2, "Bottoming"] },
    { id: "gearing", group: "Gearing", title: "Top gear", sample: "fast", needs: 6, target: [null, 0.3], ttext: () => "limiter ≤ 0.3 s per lap",
      truth: () => model.limiter, noise: 0.08, vtext: (v) => `Limiter ${Math.max(0, v).toFixed(1)} s per lap`,
      per: "straights", fix: () => ["gearing.final_drive", "decrease", 0.1, "Limiter"] },
    { id: "tire_temp_balance", group: "Tires", title: "Tire temperature, front vs rear", sample: "every", needs: 5, target: [-5, 5],
      ttext: () => `${MINUS}${Math.round(tconv(5))} … +${Math.round(tconv(5))} ${tempUnit()}`,
      truth: () => model.rearHot + 1, noise: 1.2,
      vtext: (v) => `${v >= 0 ? "Rear" : "Front"} +${Math.round(tconv(Math.abs(v)))} ${tempUnit()}`,
      per: "corners", fix: () => ["tires.pressure_rear", "decrease", 0.5, "Rear hot"] },
  ];

  const WINDOW = 12;
  const live = { t: 0, corners: 0, items: new Map(), focus: null, dirty: true, lastSent: 0 };
  function bandStatus(item, v) {
    const [lo, hi] = item.target;
    const width = lo !== null && hi !== null ? hi - lo : Math.max(0.3, Math.abs(hi ?? lo));
    const margin = width * 0.6;
    if ((lo === null || v >= lo) && (hi === null || v <= hi)) return { status: "ok", sev: 0 };
    const out = lo !== null && v < lo ? lo - v : v - hi;
    return out <= margin ? { status: "warn", sev: out / margin } : { status: "bad", sev: out / margin };
  }
  function resetLive(warm = false) {
    live.t = 0;
    live.corners = warm ? 23 : 0;
    const r = rng(42);
    for (const it of ITEMS) {
      const st = { samples: 0, ema: null, status: "collecting", pending: 0, sev: 0, recent: [] };
      if (warm && !["exit_balance", "rear_lockups", "bottoming_rear"].includes(it.id)) {
        st.samples = it.needs + 3 + Math.floor(r() * 5);
        st.ema = it.truth(0) + (r() - 0.5) * it.noise * 0.5;
        const b = bandStatus(it, st.ema);
        st.status = b.status;
        st.sev = b.sev;
        const p = { ok: 0.1, warn: 0.45, bad: 0.7 }[b.status];
        st.recent = Array.from({ length: Math.min(WINDOW, st.samples) }, () => (r() < p ? 1 : 0));
      } else if (warm) {
        st.samples = Math.floor(it.needs / 3);
        st.ema = it.truth(0);
      }
      live.items.set(it.id, st);
    }
    live.dirty = true;
  }
  resetLive(true);

  function feedLive(ev, rnd) {
    if (ev.type === "corner") live.corners += 1;
    for (const it of ITEMS) {
      if (!SAMPLERS[it.sample](ev)) continue;
      const st = live.items.get(it.id);
      const sample = it.truth(live.t) + (rnd() - 0.5) * 2 * it.noise;
      st.samples += 1;
      st.ema = st.ema === null ? sample : st.ema + (sample - st.ema) * 0.3;
      st.recent.push(bandStatus(it, sample).status === "ok" ? 0 : 1);
      if (st.recent.length > WINDOW) st.recent.shift();
      if (st.samples < it.needs) {
        st.status = "collecting";
      } else {
        const b = bandStatus(it, st.ema);
        st.sev = b.sev;
        if (st.status === "collecting") {
          st.status = b.status;
          st.pending = 0;
        } else if (b.status !== st.status) {
          st.pending += 1;
          if (st.pending >= 2) {
            st.status = b.status;
            st.pending = 0;
          }
        } else {
          st.pending = 0;
        }
      }
      live.dirty = true;
    }
  }

  function liveSnapshot() {
    let focus = null;
    let worst = -1;
    for (const want of ["bad", "warn"]) {
      for (const it of ITEMS) {
        const st = live.items.get(it.id);
        if (st.status === want && st.sev > worst) {
          worst = st.sev;
          focus = it.id;
        }
      }
      if (focus) break;
    }
    const items = ITEMS.map((it) => {
      const st = live.items.get(it.id);
      const v = st.ema;
      let recommendation = null;
      if ((st.status === "warn" || st.status === "bad") && v !== null) {
        const [setting, direction, step, word] = it.fix(v);
        const off = st.recent.reduce((a, b) => a + b, 0);
        const reason = `${word} on ${off}/${st.recent.length} ${it.per}`;
        const conf = Math.min(0.92, 0.45 + st.samples * 0.03 + (st.status === "bad" ? 0.1 : 0));
        recommendation = rec(setting, direction, step, { id: `live-${it.id}`, finding_id: it.id, reason, confidence: r2(conf) });
      }
      return {
        id: it.id, group: it.group, title: it.title, status: st.status,
        value: v === null ? null : r2(v, 3), value_text: v === null ? null : it.vtext(v),
        target_text: it.ttext(), samples: st.samples, recommendation,
      };
    });
    const win = Math.min(live.corners, 12);
    return { corners_seen: live.corners, window: { corners: win, laps: r2(win / TRACK.corners.length, 1) }, focus, items };
  }

  function applyEffects(changes) {
    for (const c of changes || []) {
      const fx = EFFECTS[c.setting];
      if (!fx || typeof c.from !== "number" || typeof c.to !== "number") continue;
      const d = c.to - c.from;
      for (const [k, coef] of Object.entries(fx)) model[k] = Math.max(0, model[k] + coef * d);
    }
  }

  // -------------------------------------------------------------- driving
  let driver = new Driver({ seed: 7, model, startFrac: 0.82, lapNumber: 4 });
  driver.bestLap = 84.912;
  driver.lastLap = 85.376;
  driver.currentLap = 0.82 * 85; // joined mid-lap: keep the lap clock plausible
  const recording = { active: false, session: null, startedMs: null, lapFrames: null, lapStartedMs: null, firstLap: true };
  const sockets = new Set();
  let packetsPerSec = 60;
  const simRand = rng(99);

  function status() {
    const driving = scenario === "driving";
    const menu = scenario === "menu";
    const sending = driving || menu;
    return {
      receiver: {
        listening: true, udp_port: 5300, public_host: "192.168.0.20",
        packets_per_sec: sending ? packetsPerSec : 0,
        last_packet_age_s: sending ? r2(0.01 + simRand() * 0.02, 3) : null,
        race_on: driving,
      },
      recording: recording.active
        ? { active: true, session_id: recording.session.id, started_at: recording.session.started_at, laps: recording.session.lapIds.length }
        : { active: false, session_id: null, started_at: null, laps: 0 },
      car: sending ? { ...CAR } : null,
      track_ordinal: sending ? TRACK_ORDINAL : null,
    };
  }

  function broadcast(msg) {
    for (const ws of sockets) ws._deliver(msg);
  }

  const TRACE_KEYS = ["t", "distance", "speed", "throttle", "brake", "steer", "gear", "rpm", "lat_g", "lon_g", "slip_angle_front", "slip_angle_rear", "slip_ratio_rear", "susp_front", "susp_rear", "pos_x", "pos_z"];
  function newLapFrames() {
    return Object.fromEntries(TRACE_KEYS.map((k) => [k, []]));
  }
  function pushFrame(f) {
    const fr = recording.lapFrames;
    const n = fr.t.length;
    fr.t.push(r2(n * 0.05, 3));
    fr.distance.push(r2(f._distance, 1));
    fr.speed.push(r2(f.speed));
    fr.throttle.push(r2(f.throttle, 3));
    fr.brake.push(r2(f.brake, 3));
    fr.steer.push(r2(f.steer, 3));
    fr.gear.push(f.gear);
    fr.rpm.push(Math.round(f.rpm));
    fr.lat_g.push(r2(f.lat_g, 3));
    fr.lon_g.push(r2(f.lon_g, 3));
    fr.slip_angle_front.push(r2((Math.abs(f.slip_angle.fl) + Math.abs(f.slip_angle.fr)) / 2, 3));
    fr.slip_angle_rear.push(r2((Math.abs(f.slip_angle.rl) + Math.abs(f.slip_angle.rr)) / 2, 3));
    fr.slip_ratio_rear.push(r2((f.slip_ratio.rl + f.slip_ratio.rr) / 2, 3));
    fr.susp_front.push(r2((f.susp.fl + f.susp.fr) / 2, 3));
    fr.susp_rear.push(r2((f.susp.rl + f.susp.rr) / 2, 3));
    fr.pos_x.push(r2(f.pos.x, 1));
    fr.pos_z.push(r2(f.pos.z, 1));
  }
  function closeLap(lapTime, kind, valid, reason) {
    const s = recording.session;
    const frames = recording.lapFrames;
    const lap = {
      id: nextLapId++, session_id: s.id, number: s.lapIds.length + 1,
      lap_time: lapTime === null ? null : r2(lapTime, 3), kind, valid, invalid_reason: reason,
      frame_count: frames.t.length * 3, started_at: iso(recording.lapStartedMs),
      _trace: { hz: 20, ...frames }, _summary: null,
    };
    laps.set(lap.id, lap);
    s.lapIds.push(lap.id);
    recording.lapFrames = newLapFrames();
    recording.lapStartedMs = Date.now();
    return lap;
  }

  function tick() {
    if (scenario !== "driving") return;
    const f = driver.step(0.05);
    live.t += 0.05;
    packetsPerSec = 59.6 + simRand() * 0.8;
    for (const ev of driver.events.splice(0)) feedLive(ev, simRand);
    if (recording.active) pushFrame(f);
    if (f._lapDone) {
      feedLive({ type: "lap" }, simRand);
      if (recording.active) {
        const first = recording.firstLap;
        recording.firstLap = false;
        const invalid = !first && simRand() < 0.12;
        const lap = closeLap(f._lapDone, first ? "partial" : "flying", !first && !invalid, first ? "Recording started mid-lap" : invalid ? "Rewind detected" : null);
        broadcast({ type: "lap_completed", session_id: recording.session.id, lap: publicLap(lap) });
        broadcast({ type: "analysis_ready", session_id: recording.session.id, lap_id: lap.id });
        broadcast({ type: "status", ...status() });
      }
    }
    const { _distance, _lapDone, ...msg } = f;
    broadcast(msg);
    const now = performance.now();
    if (live.dirty && now - live.lastSent > 500) {
      live.dirty = false;
      live.lastSent = now;
      broadcast({ type: "live_analysis", ...liveSnapshot() });
    }
  }
  const tickTimer = setInterval(tick, 50);
  const statusTimer = setInterval(() => broadcast({ type: "status", ...status() }), 1000);
  const autoTimer = setInterval(() => {
    if (!settings.auto_record) return;
    if (scenario === "driving" && !recording.active) startRecording("Auto-recorded");
  }, 2000);

  function startRecording(note) {
    const s = {
      id: nextSessionId++, started_at: new Date().toISOString(), stopped_at: null,
      car_ordinal: CAR.ordinal, car_pi: CAR.pi, car_class: CAR.class, drivetrain: CAR.drivetrain,
      track_ordinal: TRACK_ORDINAL, note: note || "", lapIds: [],
    };
    sessions.unshift(s);
    Object.assign(recording, { active: true, session: s, startedMs: Date.now(), lapFrames: newLapFrames(), lapStartedMs: Date.now(), firstLap: true });
    broadcast({ type: "status", ...status() });
    return s;
  }
  function stopRecording() {
    const s = recording.session;
    if (recording.lapFrames && recording.lapFrames.t.length > 200) {
      const lap = closeLap(null, "partial", false, "Recording stopped mid-lap");
      broadcast({ type: "lap_completed", session_id: s.id, lap: publicLap(lap) });
    }
    s.stopped_at = new Date().toISOString();
    recording.active = false;
    recording.session = null;
    broadcast({ type: "status", ...status() });
    return s;
  }

  // ------------------------------------------------------ session analysis
  function lapSummary(l) {
    if (l._summary) return l._summary;
    const tr = lapTrace(l);
    return (l._summary = summarizeTrace(tr));
  }
  function summarizeTrace(tr) {
    const n = tr.t.length;
    const ev = { spin: 0, lockF: 0, lockR: 0, bottomF: 0, bottomR: 0 };
    let pS = false, pR = false, pB = false;
    for (let i = 0; i < n; i++) {
      const s = tr.slip_ratio_rear[i] > 1, rl = tr.slip_ratio_rear[i] < -1, b = tr.susp_front[i] > 0.97;
      if (s && !pS) ev.spin++;
      if (rl && !pR) ev.lockR++;
      if (b && !pB) ev.bottomF++;
      pS = s; pR = rl; pB = b;
    }
    return { tireAvg: { fl: 88, fr: 86, rl: 95, rr: 93 }, events: ev, wearDelta: { fl: 0.003, fr: 0.003, rl: 0.003, rr: 0.003 } };
  }

  function sessionAnalysis(s) {
    const ls = sessionLaps(s);
    const flying = ls.filter((l) => l.valid && l.kind === "flying" && l.lap_time);
    const limits = [
      "No tyre pressure in Data Out",
      "One temperature per tyre: no camber read",
      "Lap validity not reported by the game",
      "Changes are relative to your current setup",
    ];
    if (flying.length < 3) {
      return { laps_analyzed: flying.length, consistency: null, findings: [], next_change: null, alternatives: [], verdict_on_last_change: null, limits };
    }
    const times = flying.map((l) => l.lap_time);
    const best = Math.min(...times);
    const mean = times.reduce((a, b) => a + b, 0) / times.length;
    const sd = Math.sqrt(times.reduce((a, b) => a + (b - mean) ** 2, 0) / times.length);
    const spins = flying.reduce((a, l) => a + lapSummary(l).events.spin, 0);
    const slowCorners = TRACK.corners.filter((c) => c.slow);
    const findings = [
      { id: "mid-understeer", title: "Understeer mid-corner in slow corners", severity: 0.64,
        evidence: `${slowCorners.length * flying.length - 3}/${slowCorners.length * flying.length} slow apexes, front slip ≥ rear + 0.15`,
        where: slowCorners.slice(0, 3).map((c) => ({ distance: r2(c.distance, 0), corner: c.number })) },
      { id: "exit-wheelspin", title: "Wheelspin out of slow corners", severity: 0.38,
        evidence: `${spins}× rear slip > 1.0 in ${flying.length} laps, turns ${slowCorners.slice(-2).map((c) => c.number).join(" and ")}`,
        where: slowCorners.slice(-2).map((c) => ({ distance: r2(c.distance + 60, 0), corner: c.number })) },
      { id: "front-lockups", title: "Front lock-ups in the heavy stops", severity: 0.27,
        evidence: `${Math.max(2, flying.length - 1)}× front slip < −1.0, turn ${TRACK.corners[1].number}`,
        where: [{ distance: r2(TRACK.corners[1].distance - 90, 0), corner: TRACK.corners[1].number }] },
    ];
    const chain = [
      () => rec("arb.front", "decrease", 2, { id: "arb-front-down", finding_id: "mid-understeer", reason: `Understeer on ${slowCorners.length * flying.length - 3}/${slowCorners.length * flying.length} slow apexes`, confidence: 0.71 }),
      () => rec("diff.accel_rear", "decrease", 5, { id: "diff-accel-down", finding_id: "exit-wheelspin", reason: `Wheelspin ${spins}× in ${flying.length} laps`, confidence: 0.58, priority: 2 }),
      () => rec("brake.pressure", "decrease", 5, { id: "brake-pressure-down", finding_id: "front-lockups", reason: `Front lock in ${Math.max(2, flying.length - 1)}/${flying.length} laps, turn ${TRACK.corners[1].number}`, confidence: 0.46, priority: 3 }),
    ];
    const depth = Math.max(0, sessions.indexOf(s)) % chain.length;
    const ordered = chain.slice(depth).concat(chain.slice(0, depth)).map((f) => f());
    return {
      laps_analyzed: flying.length,
      consistency: { best_lap: best, mean_lap: r2(mean, 3), stdev: r2(sd, 3) },
      findings,
      next_change: ordered[0],
      alternatives: ordered.slice(1, 3),
      verdict_on_last_change: null,
      limits,
    };
  }

  function lapMetrics(l) {
    const tr = lapTrace(l);
    const n = tr.t.length || 1;
    let full = 0, braking = 0, limiter = 0, maxSpeed = 0;
    const bal = { entry: [], mid: [], exit: [] };
    for (let i = 0; i < tr.t.length; i++) {
      if (tr.throttle[i] > 0.98) full++;
      if (tr.brake[i] > 0.05) braking++;
      if (tr.rpm[i] > 8450) limiter += 1 / 20;
      if (tr.speed[i] > maxSpeed) maxSpeed = tr.speed[i];
      const idx = Math.floor(tr.distance[i] / 2) % TRACK.n;
      const ph = TRACK.phaseAt[idx];
      if (ph) bal[["", "entry", "mid", "exit"][ph]].push(tr.slip_angle_front[i] - tr.slip_angle_rear[i]);
    }
    const avg = (a) => (a.length ? r2(a.reduce((x, y) => x + y, 0) / a.length / 0.5, 2) : null);
    const sum = l._summary || lapSummary(l);
    return {
      lap_time: l.lap_time, max_speed: r2(maxSpeed), full_throttle_pct: r2(full / n), braking_pct: r2(braking / n),
      corners: TRACK.corners.length, balance: { entry: avg(bal.entry), mid: avg(bal.mid), exit: avg(bal.exit) },
      wheelspin_events: sum.events.spin, lockups: { front: sum.events.lockF ?? 0, rear: sum.events.lockR ?? 0 },
      bottoming_events: (sum.events.bottomF ?? 0) + (sum.events.bottomR ?? 0), limiter_time_s: r2(limiter, 1),
      top_gear_max_rpm_pct: 0.93, tire_temp_avg: sum.tireAvg, tire_wear_delta: sum.wearDelta,
    };
  }

  function lapAnalysis(l) {
    const metrics = lapMetrics(l);
    const findings = [];
    if (metrics.balance.mid !== null && metrics.balance.mid > 0.1) {
      findings.push({ id: "mid-understeer", title: "Understeer mid-corner", severity: Math.min(1, r2(metrics.balance.mid * 2.2)),
        evidence: `Mid +${metrics.balance.mid.toFixed(2)}, target ${MINUS}0.05 … +0.10`, where: TRACK.corners.filter((c) => c.slow).slice(0, 2).map((c) => ({ distance: r2(c.distance, 0), corner: c.number })) });
    }
    if (metrics.wheelspin_events > 1) {
      findings.push({ id: "exit-wheelspin", title: "Wheelspin on exit", severity: Math.min(1, metrics.wheelspin_events * 0.12),
        evidence: `${metrics.wheelspin_events}× rear slip > 1.0`, where: [] });
    }
    if (metrics.lockups.front > 0) {
      findings.push({ id: "front-lockups", title: "Front lock-up", severity: Math.min(1, metrics.lockups.front * 0.2),
        evidence: `${metrics.lockups.front}× front lock`, where: [] });
    }
    return { lap_id: l.id, metrics, findings, valid_for_findings: l.valid && l.kind === "flying" };
  }

  // ---------------------------------------------------------------- REST
  const err = (status, code, message) => ({ status, body: { error: { code, message } } });
  const ok = (body, status = 200) => ({ status, body });

  function route(method, path, body) {
    const p = path.replace(/^\/api/, "").split("?")[0];
    const q = new URLSearchParams(path.split("?")[1] || "");
    let m;
    if (p === "/status" && method === "GET") return ok(status());
    if (p === "/recording/start" && method === "POST") {
      if (recording.active) return err(409, "already_recording", `Already recording session ${recording.session.id}.`);
      return ok(publicSession(startRecording(body?.note)));
    }
    if (p === "/recording/stop" && method === "POST") {
      if (!recording.active) return err(409, "not_recording", "Not recording.");
      return ok(publicSession(stopRecording()));
    }
    if (p === "/sessions" && method === "GET") return ok(sessions.map(publicSession));
    if ((m = p.match(/^\/sessions\/(\d+)$/))) {
      const s = sessions.find((x) => x.id === Number(m[1]));
      if (!s) return err(404, "not_found", `Session ${m[1]} doesn't exist.`);
      if (method === "GET") return ok({ ...publicSession(s), laps: sessionLaps(s).map(publicLap) });
      if (method === "PATCH") {
        if (body && "note" in body) s.note = String(body.note ?? "");
        return ok(publicSession(s));
      }
      if (method === "DELETE") {
        if (recording.active && recording.session.id === s.id) return err(409, "recording", "Stop recording before deleting this session.");
        sessions.splice(sessions.indexOf(s), 1);
        s.lapIds.forEach((id) => laps.delete(id));
        return { status: 204, body: null };
      }
    }
    if ((m = p.match(/^\/sessions\/(\d+)\/analysis$/)) && method === "GET") {
      const s = sessions.find((x) => x.id === Number(m[1]));
      if (!s) return err(404, "not_found", `Session ${m[1]} doesn't exist.`);
      return ok(sessionAnalysis(s));
    }
    if ((m = p.match(/^\/laps\/(\d+)(\/trace|\/analysis)?$/)) && method === "GET") {
      const l = laps.get(Number(m[1]));
      if (!l) return err(404, "not_found", `Lap ${m[1]} doesn't exist.`);
      if (!m[2]) return ok({ ...publicLap(l), metrics: lapMetrics(l) });
      if (m[2] === "/trace") {
        const hz = Number(q.get("hz") || 20);
        const tr = lapTrace(l);
        if (hz === 20) return ok(tr);
        const stride = Math.max(1, Math.round(20 / hz));
        const out = { hz: 20 / stride };
        for (const [k, v] of Object.entries(tr)) if (Array.isArray(v)) out[k] = v.filter((_, i) => i % stride === 0);
        return ok(out);
      }
      return ok(lapAnalysis(l));
    }
    if (p === "/live-analysis" && method === "GET") return ok(liveSnapshot());
    if (p === "/live-analysis/reset" && method === "POST") {
      // Demo: assume the player made the top-row change in game before resetting.
      const focus = ITEMS.find((it) => it.id === liveSnapshot().focus);
      const ema = focus && live.items.get(focus.id).ema;
      if (focus && ema !== null) {
        const [setting, direction, step] = focus.fix(ema);
        applyEffects([{ setting, from: 0, to: direction === "decrease" ? -step : step }]);
      }
      resetLive(false);
      const snap = liveSnapshot();
      broadcast({ type: "live_analysis", ...snap });
      return ok(snap);
    }
    if (p === "/baseline/categories" && method === "GET") return ok(CATEGORIES);
    if (p === "/baseline" && method === "GET") {
      if (!status().car) return ok({ match: null, baseline: null });
      const car = { ordinal: CAR.ordinal, name: CAR.name, division: CAR.division };
      return ok({ match: { category_id: "lmp2", how: "ordinal", confidence: "high", car }, baseline: baselineFor("lmp2") });
    }
    if ((m = p.match(/^\/baseline\/([a-z0-9_-]+)$/)) && method === "GET") {
      const b = baselineFor(m[1]);
      return b ? ok(b) : err(404, "not_found", `No baseline category "${m[1]}".`);
    }
    if (p === "/settings") {
      if (method === "GET") return ok(settings);
      if (method === "PUT") {
        const u = body?.units || {};
        if (u.speed && !["kmh", "mph"].includes(u.speed)) return err(422, "invalid_settings", "speed must be kmh or mph.");
        if (u.temperature && !["C", "F"].includes(u.temperature)) return err(422, "invalid_settings", "temperature must be C or F.");
        if (u.pressure && !["psi", "bar"].includes(u.pressure)) return err(422, "invalid_settings", "pressure must be psi or bar.");
        Object.assign(settings.units, u);
        if (typeof body?.auto_record === "boolean") settings.auto_record = body.auto_record;
        live.dirty = true;
        return ok(settings);
      }
    }
    return err(404, "not_found", `No route for ${method} ${p}.`);
  }

  async function fetchImpl(url, init = {}) {
    const method = (init.method || "GET").toUpperCase();
    const path = String(url).replace(/^https?:\/\/[^/]+/, "");
    await new Promise((res) => setTimeout(res, 60 + Math.random() * 140));
    if (scenario === "offline") throw new TypeError("Failed to fetch");
    let body = null;
    if (init.body) {
      try {
        body = JSON.parse(init.body);
      } catch {
        return new Response(JSON.stringify({ error: { code: "bad_json", message: "Body isn't JSON." } }), { status: 400 });
      }
    }
    const res = route(method, path, body);
    if (res.status === 204) return new Response(null, { status: 204 });
    return new Response(JSON.stringify(res.body), { status: res.status, headers: { "Content-Type": "application/json" } });
  }

  // ----------------------------------------------------------- WebSocket
  class MockWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.onopen = this.onmessage = this.onclose = this.onerror = null;
      setTimeout(() => {
        if (this.readyState === 3) return;
        if (scenario === "offline") {
          this.readyState = 3;
          this.onerror?.({ type: "error" });
          this.onclose?.({ code: 1006, reason: "" });
          return;
        }
        this.readyState = 1;
        sockets.add(this);
        this.onopen?.({ type: "open" });
        this._deliver({ type: "status", ...status() });
        this._deliver({ type: "live_analysis", ...liveSnapshot() });
      }, 150 + Math.random() * 150);
    }
    send() {}
    close() {
      if (this.readyState === 3) return;
      this.readyState = 3;
      sockets.delete(this);
      this.onclose?.({ code: 1000, reason: "" });
    }
    _deliver(msg) {
      if (this.readyState === 1) this.onmessage?.({ data: JSON.stringify(msg) });
    }
  }

  function setScenario(next) {
    scenario = next;
    sessionStorage.setItem(scenarioKey, next);
    if (next === "offline") {
      for (const ws of [...sockets]) {
        ws.readyState = 3;
        sockets.delete(ws);
        ws.onclose?.({ code: 1006, reason: "" });
      }
    } else {
      broadcast({ type: "status", ...status() });
    }
  }

  return {
    fetch: fetchImpl,
    WebSocket: MockWebSocket,
    get scenario() {
      return scenario;
    },
    setScenario,
    scenarios: [
      ["driving", "Driving"],
      ["menu", "In menus"],
      ["nodata", "Game not sending"],
      ["offline", "Server offline"],
    ],
    stop() {
      clearInterval(tickTimer);
      clearInterval(statusTimer);
      clearInterval(autoTimer);
    },
  };
}
