// Demo-only car-on-track simulator for mock mode. Produces plausible Data Out
// style frames at 20 Hz on a synthetic circuit. Nothing here is real data.

export function rng(seed) {
  let a = seed >>> 0 || 1;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

// ------------------------------------------------------------------ track

const CTRL = [
  [0, 0], [300, 0], [520, 0], [600, -30], [615, -110], [560, -160], [470, -170],
  [420, -215], [445, -285], [530, -300], [640, -300], [700, -345], [690, -420],
  [620, -450], [545, -430], [500, -470], [525, -560], [620, -600], [760, -610],
  [860, -640], [880, -720], [820, -780], [700, -770], [560, -740], [400, -760],
  [260, -740], [180, -680], [150, -560], [60, -480], [-40, -400], [-90, -300],
  [-80, -160], [-50, -60],
];
const DS = 2;
const A_LAT = 16.5;
const A_BRK = 13;
const VMAX = 80;

function catmullClosed(pts, per) {
  const out = [];
  const n = pts.length;
  for (let i = 0; i < n; i++) {
    const p0 = pts[(i - 1 + n) % n], p1 = pts[i], p2 = pts[(i + 1) % n], p3 = pts[(i + 2) % n];
    for (let j = 0; j < per; j++) {
      const t = j / per, t2 = t * t, t3 = t2 * t;
      const f = (a, b, c, d) => 0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3);
      out.push([f(p0[0], p1[0], p2[0], p3[0]), f(p0[1], p1[1], p2[1], p3[1])]);
    }
  }
  return out;
}

function buildTrack() {
  const dense = catmullClosed(CTRL, 40);
  dense.push(dense[0]);
  const cum = [0];
  for (let i = 1; i < dense.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(dense[i][0] - dense[i - 1][0], dense[i][1] - dense[i - 1][1]));
  }
  const length = cum[cum.length - 1];
  const n = Math.floor(length / DS);
  const x = new Float64Array(n), z = new Float64Array(n);
  let j = 0;
  for (let i = 0; i < n; i++) {
    const target = i * DS;
    while (cum[j + 1] < target) j++;
    const f = (target - cum[j]) / (cum[j + 1] - cum[j] || 1);
    x[i] = dense[j][0] + (dense[j + 1][0] - dense[j][0]) * f;
    z[i] = dense[j][1] + (dense[j + 1][1] - dense[j][1]) * f;
  }
  // curvature (signed), smoothed
  const head = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const k = (i + 1) % n;
    head[i] = Math.atan2(z[k] - z[i], x[k] - x[i]);
  }
  const raw = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let d = head[(i + 1) % n] - head[i];
    while (d > Math.PI) d -= 2 * Math.PI;
    while (d < -Math.PI) d += 2 * Math.PI;
    raw[i] = d / DS;
  }
  const W = 6;
  const k = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let sum = 0;
    for (let o = -W; o <= W; o++) sum += raw[(i + o + n) % n];
    k[i] = sum / (2 * W + 1);
  }
  // speed profile
  const v = new Float64Array(n);
  for (let i = 0; i < n; i++) v[i] = Math.min(VMAX, Math.sqrt(A_LAT / Math.max(Math.abs(k[i]), 1e-5)));
  for (let pass = 0; pass < 2; pass++) {
    for (let i = 0; i < n; i++) {
      const a = 9.5 * Math.pow(1 - Math.min(v[i], VMAX) / (VMAX * 1.05), 0.8) + 0.4;
      const next = (i + 1) % n;
      v[next] = Math.min(v[next], Math.sqrt(v[i] * v[i] + 2 * a * DS));
    }
    for (let i = n - 1; i >= 0; i--) {
      const next = (i + 1) % n;
      v[i] = Math.min(v[i], Math.sqrt(v[next] * v[next] + 2 * A_BRK * DS));
    }
  }
  // corners
  const corners = [];
  const K = 1 / 320;
  let i0 = -1;
  for (let i = 0; i < n; i++) {
    const inC = Math.abs(k[i]) > K;
    if (inC && i0 < 0) i0 = i;
    if ((!inC || i === n - 1) && i0 >= 0) {
      const i1 = i;
      if ((i1 - i0) * DS > 30) {
        let apex = i0;
        for (let q = i0; q < i1; q++) if (v[q] < v[apex]) apex = q;
        const prev = corners[corners.length - 1];
        if (prev && (i0 - prev.end) * DS < 50 && Math.sign(k[apex]) === prev.dir) {
          prev.end = i1;
          if (v[apex] < v[prev.apex]) prev.apex = apex;
        } else {
          corners.push({ start: i0, end: i1, apex, dir: Math.sign(k[apex]) });
        }
      }
      i0 = -1;
    }
  }
  corners.forEach((c, idx) => {
    c.number = idx + 1;
    c.apexSpeed = v[c.apex];
    c.slow = c.apexSpeed < 34;
    c.distance = c.apex * DS;
  });
  const cornerAt = new Int16Array(n).fill(-1);
  const phaseAt = new Uint8Array(n); // 0 straight, 1 entry, 2 mid, 3 exit
  corners.forEach((c, idx) => {
    let b = c.start;
    while (v[(b - 1 + n) % n] > v[b] + 0.05 && (c.start - b) * DS < 220) b--;
    for (let q = b; q <= c.end + 20; q++) {
      const ii = (q + n) % n;
      cornerAt[ii] = idx;
      const fromApex = (q - c.apex) * DS;
      phaseAt[ii] = fromApex < -20 ? 1 : fromApex <= 20 ? 2 : 3;
    }
  });
  const bumps = [Math.floor(n * 0.31), Math.floor(n * 0.62), Math.floor(n * 0.86)];
  return { n, length: n * DS, x, z, k, v, corners, cornerAt, phaseAt, bumps };
}

export const TRACK = buildTrack();

// ------------------------------------------------------------- car model

/** Handling character of the demo car; tune changes nudge these numbers. */
export function defaultModel() {
  return {
    entryU: 0.04,
    midSlowU: 0.21,
    midFastU: 0.12,
    exitO: 0.04,
    wheelspin: 0.42,
    lockFront: 0.55,
    lockRear: 0.05,
    rearStep: 0.38,
    bottomFront: 0.2,
    bottomRear: 0.05,
    limiter: 0.42,
    rearHot: 6,
  };
}

const GEAR_UP = [20, 30, 40, 51, 63, 76];
const MAX_RPM = 8600;
const IDLE = 950;

function gearFor(v) {
  for (let g = 0; g < GEAR_UP.length; g++) if (v < GEAR_UP[g] * 0.985) return g + 1;
  return GEAR_UP.length;
}

/**
 * One car driving laps. step(dt) advances time and returns a frame in the
 * shape of the /ws/live "telemetry" message (canonical units) plus a few
 * private fields prefixed with "_".
 */
export class Driver {
  constructor({ seed = 1, drivetrain = "RWD", model = defaultModel(), startFrac = 0, lapNumber = 0, coldTyres = false } = {}) {
    this.r = rng(seed);
    this.drivetrain = drivetrain;
    this.model = model;
    this.s = startFrac * TRACK.length;
    this.t = 0;
    this.lapNumber = lapNumber;
    this.currentLap = 0;
    this.lastLap = 0;
    this.bestLap = 0;
    this.lapFactor = this._newFactor();
    this.speedScale = 1;
    const base = coldTyres ? 52 : 84;
    this.temps = [base, base + 1, base + 3, base + 4];
    this.wear = [1, 1, 1, 1];
    this.lockTimer = 0;
    this.lockAxle = "front";
    this.spinTimer = 0;
    this.v = TRACK.v[Math.floor(this.s / 2) % TRACK.n] * 0.9;
    this.prevIndex = Math.floor(this.s / 2) % TRACK.n;
    this.events = [];
  }

  _newFactor() {
    return 0.982 + this.r() * 0.024;
  }

  step(dt) {
    const T = TRACK;
    const m = this.model;
    const r = this.r;
    const idx = Math.floor(this.s / 2) % T.n;
    const next = (idx + 3) % T.n;
    const target = T.v[idx] * this.lapFactor * this.speedScale;
    this.v += (target - this.v) * Math.min(1, dt * 6);
    const v = Math.max(3, this.v + (r() - 0.5) * 0.15);
    const dvds = (T.v[next] - T.v[idx]) / (3 * 2);
    const ax = v * dvds; // m/s^2 along track
    const k = T.k[idx];
    const latG = (v * v * k) / 9.81;
    const lonG = ax / 9.81 + (r() - 0.5) * 0.03;
    const phase = T.phaseAt[idx];
    const ci = T.cornerAt[idx];
    const corner = ci >= 0 ? T.corners[ci] : null;

    let throttle = 0, brake = 0;
    if (ax > 0.35) throttle = clamp(0.6 + ax / 6, 0, 1);
    else if (ax < -1.2) brake = clamp(-ax / A_BRK + 0.05, 0, 1);
    else throttle = clamp(0.38 + (r() - 0.5) * 0.08, 0, 1);
    if (v > 74 && throttle > 0.9) throttle = 1;
    const steer = clamp(k * 38 + (r() - 0.5) * 0.02, -1, 1);

    // balance: + understeer (front slides more), - oversteer
    let bal = 0;
    if (corner) {
      if (phase === 1) bal = m.entryU;
      else if (phase === 2) bal = corner.slow ? m.midSlowU : m.midFastU;
      else bal = -m.exitO * (0.5 + throttle);
    }
    bal += (r() - 0.5) * 0.06;
    const grip = Math.abs(latG) / 1.68;
    const sign = Math.sign(k) || 1;
    const fA = grip * (0.86 + bal) + r() * 0.03;
    const rA = grip * (0.86 - bal) + r() * 0.03;
    const outsideLeft = sign < 0; // turning right loads the left side
    const slipAngle = {
      fl: sign * fA * (outsideLeft ? 1.08 : 0.92),
      fr: sign * fA * (outsideLeft ? 0.92 : 1.08),
      rl: sign * rA * (outsideLeft ? 1.08 : 0.92),
      rr: sign * rA * (outsideLeft ? 0.92 : 1.08),
    };

    // wheelspin and lock-ups as short events
    if (this.spinTimer <= 0 && phase === 3 && throttle > 0.7 && v < 40 && r() < m.wheelspin * 0.025) this.spinTimer = 0.25 + r() * 0.5;
    if (this.lockTimer <= 0 && brake > 0.7 && v > 25) {
      if (r() < m.lockFront * 0.006) { this.lockTimer = 0.2 + r() * 0.35; this.lockAxle = "front"; }
      else if (r() < m.lockRear * 0.006) { this.lockTimer = 0.2 + r() * 0.3; this.lockAxle = "rear"; }
    }
    const spin = this.spinTimer > 0 ? 1.15 + r() * 0.5 : 0;
    const lock = this.lockTimer > 0 ? -(1.1 + r() * 0.3) : 0;
    this.spinTimer -= dt;
    this.lockTimer -= dt;
    const driven = this.drivetrain === "FWD" ? ["fl", "fr"] : this.drivetrain === "AWD" ? ["fl", "fr", "rl", "rr"] : ["rl", "rr"];
    const slipRatio = { fl: 0, fr: 0, rl: 0, rr: 0 };
    for (const w of Object.keys(slipRatio)) {
      let x = driven.includes(w) ? throttle * 0.22 : 0;
      x -= brake * 0.32;
      x += (r() - 0.5) * 0.04;
      if (spin && driven.includes(w)) x = spin * (w.endsWith("l") ? 1 : 0.9);
      if (lock && ((this.lockAxle === "front" && w[0] === "f") || (this.lockAxle === "rear" && w[0] === "r"))) x = lock;
      slipRatio[w] = x;
    }

    // suspension, bumps
    let suspF = 0.46 - lonG * 0.09 + Math.abs(latG) * 0.06 + (r() - 0.5) * 0.02;
    let suspR = 0.46 + lonG * 0.06 + Math.abs(latG) * 0.05 + (r() - 0.5) * 0.02;
    for (const b of T.bumps) {
      if (Math.abs(idx - b) < 3) {
        suspF += 0.4 + m.bottomFront * 0.8 * r();
        suspR += 0.38 + m.bottomRear * 0.8 * r();
      }
    }
    const susp = { fl: clamp(suspF, 0, 1), fr: clamp(suspF - 0.01, 0, 1), rl: clamp(suspR, 0, 1), rr: clamp(suspR - 0.01, 0, 1) };

    // tyres
    const wheels = ["fl", "fr", "rl", "rr"];
    wheels.forEach((w, i) => {
      const outside = (w.endsWith("l") && outsideLeft) || (w.endsWith("r") && !outsideLeft);
      const load = Math.abs(latG) * (outside ? 1.25 : 0.7);
      let target = 70 + load * 13 + (w[0] === "f" ? brake * 12 : throttle * 6) + (w[0] === "r" ? m.rearHot : 0);
      if (Math.abs(slipRatio[w]) > 1) target += 30;
      this.temps[i] += (target - this.temps[i]) * Math.min(1, dt / 7);
      this.wear[i] = Math.max(0, this.wear[i] - dt * (0.00002 + load * 0.00001));
    });

    // gear / rpm
    const gear = gearFor(v);
    const lo = gear > 1 ? GEAR_UP[gear - 2] : 0;
    const hi = GEAR_UP[gear - 1];
    let rpm = IDLE + ((v - lo * 0.75) / (hi - lo * 0.75)) * (8250 - IDLE);
    if (gear === GEAR_UP.length && v > hi * 0.985) rpm = 8480 + r() * 60;
    rpm = clamp(rpm, IDLE, MAX_RPM);

    // advance
    this.s += v * dt;
    this.t += dt;
    this.currentLap += dt;
    let lapDone = null;
    if (this.s >= T.length) {
      this.s -= T.length;
      lapDone = this.currentLap;
      this.lastLap = this.currentLap;
      if (!this.bestLap || this.lastLap < this.bestLap) this.bestLap = this.lastLap;
      this.currentLap = 0;
      this.lapNumber += 1;
      this.lapFactor = this._newFactor();
    }

    // corner events (for the live analyzer)
    const newIdx = Math.floor(this.s / 2) % T.n;
    for (const c of T.corners) {
      const crossed = this.prevIndex <= c.end + 20 && newIdx > c.end + 20 && newIdx - this.prevIndex < 50;
      if (crossed) this.events.push({ type: "corner", corner: c });
    }
    for (const b of T.bumps) {
      if (this.prevIndex < b && newIdx >= b) this.events.push({ type: "bump" });
    }
    this.prevIndex = newIdx;

    const pos = { x: T.x[idx], z: T.z[idx] };
    return {
      type: "telemetry",
      t: this.t,
      speed: v,
      rpm,
      max_rpm: MAX_RPM,
      gear,
      throttle,
      brake,
      steer,
      lap_number: this.lapNumber + 1, // API lap numbers are 1-based
      current_lap: this.currentLap,
      last_lap: this.lastLap,
      best_lap: this.bestLap,
      race_position: 1,
      lat_g: latG,
      lon_g: lonG,
      tire_temp: { fl: this.temps[0], fr: this.temps[1], rl: this.temps[2], rr: this.temps[3] },
      tire_wear: { fl: this.wear[0], fr: this.wear[1], rl: this.wear[2], rr: this.wear[3] },
      slip_angle: slipAngle,
      slip_ratio: slipRatio,
      susp,
      pos,
      _distance: this.s,
      _lapDone: lapDone,
    };
  }
}

/** Drive one lap offline and return a Trace (canonical units) plus its lap time. */
export function simulateLap({ seed, model, drivetrain = "RWD", kind = "flying", hz = 20, partial = 1, pace = 1 }) {
  const d = new Driver({ seed, model, drivetrain, startFrac: 0, coldTyres: kind === "out" });
  d.speedScale = kind === "out" ? 0.82 * pace : pace;
  const dt = 1 / hz;
  const keys = ["t", "distance", "speed", "throttle", "brake", "steer", "gear", "rpm", "lat_g", "lon_g", "slip_angle_front", "slip_angle_rear", "slip_ratio_rear", "susp_front", "susp_rear", "pos_x", "pos_z"];
  const tr = Object.fromEntries(keys.map((k) => [k, []]));
  const stopAt = TRACK.length * partial;
  let distance = 0;
  const tempSum = { fl: 0, fr: 0, rl: 0, rr: 0 };
  let frames = 0;
  const ev = { spin: 0, lockF: 0, lockR: 0, bottomF: 0, bottomR: 0, limiter: 0 };
  let prev = { spin: false, lockF: false, lockR: false, bottomF: false, bottomR: false };
  let wear0 = null, wear1 = null;
  for (let guard = 0; guard < 200 * hz; guard++) {
    if (kind === "in" && distance > TRACK.length * 0.45) d.speedScale = 0.78 * pace;
    const f = d.step(dt);
    if (f._lapDone || distance >= stopAt) break;
    distance = f._distance;
    frames++;
    const now = {
      spin: (f.slip_ratio.rl + f.slip_ratio.rr) / 2 > 1,
      lockF: Math.min(f.slip_ratio.fl, f.slip_ratio.fr) < -1,
      lockR: Math.min(f.slip_ratio.rl, f.slip_ratio.rr) < -1,
      bottomF: f.susp.fl > 0.97,
      bottomR: f.susp.rl > 0.97,
    };
    if (now.spin && !prev.spin) ev.spin++;
    if (now.lockF && !prev.lockF) ev.lockF++;
    if (now.lockR && !prev.lockR) ev.lockR++;
    if (now.bottomF && !prev.bottomF) ev.bottomF++;
    if (now.bottomR && !prev.bottomR) ev.bottomR++;
    if (f.rpm > 8450) ev.limiter += dt;
    prev = now;
    if (!wear0) wear0 = { ...f.tire_wear };
    wear1 = f.tire_wear;
    for (const w of ["fl", "fr", "rl", "rr"]) tempSum[w] += f.tire_temp[w];
    tr.t.push(+(frames * dt).toFixed(3));
    tr.distance.push(+distance.toFixed(1));
    tr.speed.push(+f.speed.toFixed(2));
    tr.throttle.push(+f.throttle.toFixed(3));
    tr.brake.push(+f.brake.toFixed(3));
    tr.steer.push(+f.steer.toFixed(3));
    tr.gear.push(f.gear);
    tr.rpm.push(Math.round(f.rpm));
    tr.lat_g.push(+f.lat_g.toFixed(3));
    tr.lon_g.push(+f.lon_g.toFixed(3));
    tr.slip_angle_front.push(+((Math.abs(f.slip_angle.fl) + Math.abs(f.slip_angle.fr)) / 2).toFixed(3));
    tr.slip_angle_rear.push(+((Math.abs(f.slip_angle.rl) + Math.abs(f.slip_angle.rr)) / 2).toFixed(3));
    tr.slip_ratio_rear.push(+((f.slip_ratio.rl + f.slip_ratio.rr) / 2).toFixed(3));
    tr.susp_front.push(+((f.susp.fl + f.susp.fr) / 2).toFixed(3));
    tr.susp_rear.push(+((f.susp.rl + f.susp.rr) / 2).toFixed(3));
    tr.pos_x.push(+f.pos.x.toFixed(1));
    tr.pos_z.push(+f.pos.z.toFixed(1));
  }
  const lapTime = frames * dt;
  const tireAvg = Object.fromEntries(Object.entries(tempSum).map(([w, s]) => [w, +(s / Math.max(1, frames)).toFixed(1)]));
  const wearDelta = Object.fromEntries(["fl", "fr", "rl", "rr"].map((w) => [w, +((wear0?.[w] ?? 1) - (wear1?.[w] ?? 1)).toFixed(4)]));
  return { trace: { hz, ...tr }, lapTime, frames, tireAvg, events: ev, wearDelta };
}
