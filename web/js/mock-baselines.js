// Demo baseline setups for ?mock=1. Shapes follow GET /api/baseline* (see
// pitwall/baselines/types.py); the numbers and notes are invented for the
// demo and are not tuning advice.

export const CATEGORIES = [
  { id: "lmp2", name: "LMP2 and early LMP prototypes", description: "Closed-wheel prototypes with high downforce.", divisions: ["Forza P2", "Early LMP"], drivetrains: ["RWD"] },
  { id: "gt3", name: "GT3 / GTE", description: "Production-based race cars, mid downforce.", divisions: ["Forza GT"], drivetrains: ["RWD", "AWD"] },
  { id: "touring", name: "Touring cars", description: "Front-engined saloons on slicks, low downforce.", divisions: ["Forza Touring Car"], drivetrains: ["FWD", "RWD"] },
];

// Menu order, as the game lists them.
const ROWS = [
  ["tires.pressure_front", "Tires", "Tire Pressure", "Front", "psi"],
  ["tires.pressure_rear", "Tires", "Tire Pressure", "Rear", "psi"],
  ["gearing.final_drive", "Gearing", "Final Drive", null, ""],
  ["alignment.camber_front", "Alignment", "Camber", "Front", "°"],
  ["alignment.camber_rear", "Alignment", "Camber", "Rear", "°"],
  ["alignment.toe_front", "Alignment", "Toe", "Front", "°"],
  ["alignment.toe_rear", "Alignment", "Toe", "Rear", "°"],
  ["alignment.caster", "Alignment", "Caster", "Front", "°"],
  ["arb.front", "Anti-roll Bars", "Anti-roll Bars", "Front", ""],
  ["arb.rear", "Anti-roll Bars", "Anti-roll Bars", "Rear", ""],
  ["springs.front", "Springs", "Springs", "Front", "lb/in"],
  ["springs.rear", "Springs", "Springs", "Rear", "lb/in"],
  ["springs.ride_height_front", "Springs", "Ride Height", "Front", "in"],
  ["springs.ride_height_rear", "Springs", "Ride Height", "Rear", "in"],
  ["damping.rebound_front", "Damping", "Rebound Stiffness", "Front", ""],
  ["damping.rebound_rear", "Damping", "Rebound Stiffness", "Rear", ""],
  ["damping.bump_front", "Damping", "Bump Stiffness", "Front", ""],
  ["damping.bump_rear", "Damping", "Bump Stiffness", "Rear", ""],
  ["geometry.roll_center_front", "Geometry", "Roll Center Height Offset", "Front", "in"],
  ["geometry.roll_center_rear", "Geometry", "Roll Center Height Offset", "Rear", "in"],
  ["geometry.anti_front", "Geometry", "Anti-dive", "Front", "%"],
  ["geometry.anti_rear", "Geometry", "Anti-squat", "Rear", "%"],
  ["aero.front", "Aero", "Downforce", "Front", "lb"],
  ["aero.rear", "Aero", "Downforce", "Rear", "lb"],
  ["brake.balance", "Brake", "Braking Balance", null, "% front"],
  ["brake.pressure", "Brake", "Braking Pressure", null, "%"],
  ["diff.accel_front", "Differential", "Acceleration", "Front", "%"],
  ["diff.decel_front", "Differential", "Deceleration", "Front", "%"],
  ["diff.accel_rear", "Differential", "Acceleration", "Rear", "%"],
  ["diff.decel_rear", "Differential", "Deceleration", "Rear", "%"],
];

const V = (value, range = null, note = "") => ({ value, range, relative: null, note, basis: "published" });
const R = (relative, note = "") => ({ value: null, range: null, relative, note, basis: "published" });
const N = (note) => ({ value: null, range: null, relative: null, note, basis: "published" });

// Long on purpose: real notes run to several sentences and live in tooltips.
const NOTE = {
  pressure: "Demo note. The menu sets the running pressure, so this is what the tyres carry on track. Keep front and rear equal to start, then adjust in small steps.",
  finalDrive: "Demo note. Start from the ratio the build gives you. On the limiter before the braking point: lower it. Top gear never near the limiter: raise it.",
  camber: "Demo note. Static camber; fine-tune with the in-game tyre temperature view, since Data Out has one temperature per tyre.",
  toe: "Demo note. Zero toe to start.",
  caster: "Demo note. Race cars run a little less caster than road cars.",
  bars: "Demo note. Prototypes run much stiffer bars than GT cars; heavier cars want stiffer bars, lighter ones softer.",
  springs: "Demo note. Spring scales differ per car, so work from the weight shown in the tuning menu, or start around the middle of the slider.",
  rideHeight: "Demo note. As low as the slider allows without bottoming; raise a notch if the car scrapes.",
  damping: "Demo note. Bump about a third of rebound; rear rebound a step above the front.",
  geometry: "Demo note. Leave at the car's default; only special builds need geometry changes.",
  aero: "Demo note. Start near maximum downforce, then trim both ends together for long straights.",
  brakes: "Demo note. Move balance forward if the rear locks, back if the fronts lock.",
  diff: "Demo note. A stiffer acceleration lock helps traction out of slow corners; deceleration stays low for turn-in.",
};

const DATA = {
  lmp2: {
    drivetrain: "RWD",
    confidence: "medium",
    values: {
      "tires.pressure_front": V(28.0, [27.0, 30.0], NOTE.pressure),
      "tires.pressure_rear": V(28.0, [27.0, 30.0], NOTE.pressure),
      "gearing.final_drive": N(NOTE.finalDrive),
      "alignment.camber_front": V(-1.8, [-2.5, -1.0], NOTE.camber),
      "alignment.camber_rear": V(-1.3, [-2.0, -0.5], NOTE.camber),
      "alignment.toe_front": V(0.0, null, NOTE.toe),
      "alignment.toe_rear": V(0.0, null, NOTE.toe),
      "alignment.caster": V(6.0, [5.5, 6.5], NOTE.caster),
      "arb.front": V(32, [25, 44], NOTE.bars),
      "arb.rear": V(35, [27, 46], NOTE.bars),
      "springs.front": N(NOTE.springs),
      "springs.rear": N(NOTE.springs),
      "springs.ride_height_front": N(NOTE.rideHeight),
      "springs.ride_height_rear": N(NOTE.rideHeight),
      "damping.rebound_front": V(10.0, [8.0, 12.0], NOTE.damping),
      "damping.rebound_rear": V(11.0, [9.0, 13.0], NOTE.damping),
      "damping.bump_front": V(3.5, [2.0, 5.0], NOTE.damping),
      "damping.bump_rear": V(4.0, [2.5, 5.5], NOTE.damping),
      "geometry.roll_center_front": N(NOTE.geometry),
      "geometry.roll_center_rear": N(NOTE.geometry),
      "geometry.anti_front": N(NOTE.geometry),
      "geometry.anti_rear": N(NOTE.geometry),
      "aero.front": R("≈95% of slider (60–100%)", NOTE.aero),
      "aero.rear": R("≈100% of slider (60–100%)", NOTE.aero),
      "brake.balance": V(46, [43, 50], NOTE.brakes),
      "brake.pressure": V(105, [100, 140], NOTE.brakes),
      "diff.accel_rear": V(80, [60, 95], NOTE.diff),
      "diff.decel_rear": V(8, [0, 18], NOTE.diff),
    },
    notes: ["Demo values. Starting points, not optimal tunes.", "Tyre pressures are running pressures."],
    sources: [
      { title: "Demo source A", url: "https://example.org/pitwall-demo/lmp2", used_for: "demo rows" },
      { title: "Demo source B", url: "https://example.org/pitwall-demo/prototypes", used_for: "demo damping and differential" },
    ],
  },
  gt3: {
    drivetrain: "RWD",
    confidence: "medium",
    values: {
      "tires.pressure_front": V(28.5, [27.5, 30.0], NOTE.pressure),
      "tires.pressure_rear": V(28.0, [27.0, 29.5], NOTE.pressure),
      "gearing.final_drive": N(NOTE.finalDrive),
      "alignment.camber_front": V(-2.4, [-3.0, -1.8], NOTE.camber),
      "alignment.camber_rear": V(-1.6, [-2.2, -1.0], NOTE.camber),
      "alignment.toe_front": V(0.0, null, NOTE.toe),
      "alignment.toe_rear": V(0.1, [0.0, 0.2], NOTE.toe),
      "alignment.caster": V(6.2, [5.5, 7.0], NOTE.caster),
      "arb.front": V(24, [18, 30], NOTE.bars),
      "arb.rear": V(20, [15, 26], NOTE.bars),
      "springs.front": R("≈55% of slider (40–70%)", NOTE.springs),
      "springs.rear": R("≈50% of slider (35–65%)", NOTE.springs),
      "springs.ride_height_front": N(NOTE.rideHeight),
      "springs.ride_height_rear": N(NOTE.rideHeight),
      "damping.rebound_front": V(9.5, [8.0, 11.0], NOTE.damping),
      "damping.rebound_rear": V(10.0, [8.5, 11.5], NOTE.damping),
      "damping.bump_front": V(3.0, [2.0, 4.5], NOTE.damping),
      "damping.bump_rear": V(3.5, [2.5, 5.0], NOTE.damping),
      "geometry.roll_center_front": N(NOTE.geometry),
      "geometry.roll_center_rear": N(NOTE.geometry),
      "geometry.anti_front": N(NOTE.geometry),
      "geometry.anti_rear": N(NOTE.geometry),
      "aero.front": R("≈70% of slider (50–90%)", NOTE.aero),
      "aero.rear": R("≈75% of slider (55–95%)", NOTE.aero),
      "brake.balance": V(50, [47, 54], NOTE.brakes),
      "brake.pressure": V(110, [100, 130], NOTE.brakes),
      "diff.accel_rear": V(60, [45, 75], NOTE.diff),
      "diff.decel_rear": V(15, [5, 30], NOTE.diff),
    },
    notes: ["Demo values. Starting points, not optimal tunes."],
    sources: [{ title: "Demo source C", url: "https://example.org/pitwall-demo/gt3", used_for: "demo rows" }],
  },
  touring: {
    drivetrain: "FWD",
    confidence: "low",
    values: {
      "tires.pressure_front": V(29.0, [28.0, 30.5], NOTE.pressure),
      "tires.pressure_rear": V(28.0, [27.0, 29.5], NOTE.pressure),
      "gearing.final_drive": N(NOTE.finalDrive),
      "alignment.camber_front": V(-2.2, [-2.8, -1.6], NOTE.camber),
      "alignment.camber_rear": V(-1.2, [-1.8, -0.6], NOTE.camber),
      "alignment.toe_front": V(0.0, null, NOTE.toe),
      "alignment.toe_rear": V(-0.1, [-0.3, 0.0], "Demo note. A little toe-out at the rear helps a front-driven car rotate."),
      "alignment.caster": V(5.5, [5.0, 6.5], NOTE.caster),
      "arb.front": V(14, [8, 20], NOTE.bars),
      "arb.rear": V(28, [20, 36], NOTE.bars),
      "springs.front": R("≈50% of slider (35–65%)", NOTE.springs),
      "springs.rear": R("≈60% of slider (45–75%)", NOTE.springs),
      "springs.ride_height_front": N(NOTE.rideHeight),
      "springs.ride_height_rear": N(NOTE.rideHeight),
      "damping.rebound_front": V(8.5, [7.0, 10.0], NOTE.damping),
      "damping.rebound_rear": V(9.5, [8.0, 11.0], NOTE.damping),
      "damping.bump_front": V(3.0, [2.0, 4.0], NOTE.damping),
      "damping.bump_rear": V(3.5, [2.5, 4.5], NOTE.damping),
      "geometry.roll_center_front": N(NOTE.geometry),
      "geometry.roll_center_rear": N(NOTE.geometry),
      "geometry.anti_front": N(NOTE.geometry),
      "geometry.anti_rear": N(NOTE.geometry),
      "aero.front": R("≈50% of slider (30–70%)", NOTE.aero),
      "aero.rear": R("≈50% of slider (30–70%)", NOTE.aero),
      "brake.balance": V(56, [52, 60], NOTE.brakes),
      "brake.pressure": V(100, [90, 115], NOTE.brakes),
      "diff.accel_front": V(30, [20, 45], NOTE.diff),
      "diff.decel_front": V(10, [0, 20], NOTE.diff),
    },
    notes: ["Demo values. Starting points, not optimal tunes."],
    sources: [{ title: "Demo source D", url: "https://example.org/pitwall-demo/touring", used_for: "demo rows" }],
  },
};

export function baselineFor(categoryId) {
  const category = CATEGORIES.find((c) => c.id === categoryId);
  if (!category) return null;
  const d = DATA[category.id];
  const settings = [];
  for (const [key, section, label, axle, unit] of ROWS) {
    const v = d.values[key];
    if (!v) continue;
    settings.push({ key, section, label, axle, unit, ...v });
  }
  return { category, unit_system: "imperial", drivetrain: d.drivetrain, settings, notes: d.notes, sources: d.sources, confidence: d.confidence };
}
