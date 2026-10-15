// Demo baseline setups for ?mock=1. Shapes follow GET /api/baseline*; the
// numbers are invented for the demo and are not tuning advice.

export const CATEGORIES = [
  { id: "lmp2", name: "LMP2 / Forza P2 prototypes", description: "Closed-wheel prototypes with high downforce.", divisions: ["Forza P2"], drivetrains: ["RWD"] },
  { id: "gt3", name: "GT3 / Forza GT", description: "Production-based race cars, mid downforce.", divisions: ["Forza GT"], drivetrains: ["RWD", "AWD"] },
  { id: "touring", name: "Touring cars", description: "Front-engined saloons on slicks, low downforce.", divisions: ["Forza Touring Car"], drivetrains: ["FWD", "RWD"] },
];

// key, section, label, axle, unit, then per category: [value, range, relative, note]
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
  ["aero.front", "Aero", "Downforce", "Front", "lb"],
  ["aero.rear", "Aero", "Downforce", "Rear", "lb"],
  ["brake.balance", "Brake", "Braking Balance", null, "% front"],
  ["brake.pressure", "Brake", "Braking Pressure", null, "%"],
  ["diff.accel_front", "Differential", "Acceleration", "Front", "%"],
  ["diff.decel_front", "Differential", "Deceleration", "Front", "%"],
  ["diff.accel_rear", "Differential", "Acceleration", "Rear", "%"],
  ["diff.decel_rear", "Differential", "Deceleration", "Rear", "%"],
];

const V = (value, range = null, note = "") => ({ value, range, relative: null, note });
const R = (relative, note = "") => ({ value: null, range: null, relative, note });

const DATA = {
  lmp2: {
    confidence: "medium",
    values: {
      "tires.pressure_front": V(27.5, [26.5, 28.5], "Hot ≈ 33 psi"),
      "tires.pressure_rear": V(27.0, [26.0, 28.0], "Hot ≈ 33 psi"),
      "gearing.final_drive": R("≈ 40% of slider", "Top gear: no limiter"),
      "alignment.camber_front": V(-2.8, [-3.2, -2.4]),
      "alignment.camber_rear": V(-1.8, [-2.2, -1.4]),
      "alignment.toe_front": V(0.0, [-0.1, 0.1]),
      "alignment.toe_rear": V(0.1, [0.0, 0.2]),
      "alignment.caster": V(6.5, [6.0, 7.0]),
      "arb.front": V(22, [18, 26]),
      "arb.rear": V(18, [14, 22]),
      "springs.front": R("≈ 60% of slider"),
      "springs.rear": R("≈ 55% of slider"),
      "springs.ride_height_front": R("2 clicks above min", "Raise if it bottoms"),
      "springs.ride_height_rear": R("3 clicks above min", "Raise if it bottoms"),
      "damping.rebound_front": V(11.0, [9.5, 12.5]),
      "damping.rebound_rear": V(9.5, [8.0, 11.0]),
      "damping.bump_front": V(7.0, [6.0, 8.0], "≈ 60–65% of rebound"),
      "damping.bump_rear": V(6.0, [5.0, 7.0], "≈ 60–65% of rebound"),
      "aero.front": R("≈ 70% of slider"),
      "aero.rear": R("≈ 75% of slider"),
      "brake.balance": V(52, [50, 54]),
      "brake.pressure": V(100, [95, 110]),
      "diff.accel_rear": V(45, [35, 55]),
      "diff.decel_rear": V(20, [10, 30]),
    },
    notes: ["Demo values"],
    sources: [{ title: "Demo source A", url: "https://example.org/pitwall-demo/lmp2" }, { title: "Demo source B", url: "https://example.org/pitwall-demo/prototypes" }],
  },
  gt3: {
    confidence: "medium",
    values: {
      "tires.pressure_front": V(28.0, [27.0, 29.0], "Hot ≈ 33 psi"),
      "tires.pressure_rear": V(27.5, [26.5, 28.5], "Hot ≈ 33 psi"),
      "gearing.final_drive": R("≈ 45% of slider", "Top gear: no limiter"),
      "alignment.camber_front": V(-2.5, [-3.0, -2.0]),
      "alignment.camber_rear": V(-1.6, [-2.0, -1.2]),
      "alignment.toe_front": V(0.0, [-0.1, 0.1]),
      "alignment.toe_rear": V(0.1, [0.0, 0.2]),
      "alignment.caster": V(6.0, [5.5, 6.8]),
      "arb.front": V(20, [16, 25]),
      "arb.rear": V(16, [12, 20]),
      "springs.front": R("≈ 55% of slider"),
      "springs.rear": R("≈ 50% of slider"),
      "springs.ride_height_front": R("3 clicks above min", "Raise if it bottoms"),
      "springs.ride_height_rear": R("4 clicks above min", "Raise if it bottoms"),
      "damping.rebound_front": V(10.0, [8.5, 11.5]),
      "damping.rebound_rear": V(8.5, [7.0, 10.0]),
      "damping.bump_front": V(6.5, [5.5, 7.5]),
      "damping.bump_rear": V(5.5, [4.5, 6.5]),
      "aero.front": R("≈ 60% of slider"),
      "aero.rear": R("≈ 65% of slider"),
      "brake.balance": V(53, [51, 55]),
      "brake.pressure": V(100, [95, 110]),
      "diff.accel_rear": V(50, [40, 60], "AWD: same both axles"),
      "diff.decel_rear": V(25, [15, 35]),
    },
    notes: ["Demo values"],
    sources: [{ title: "Demo source C", url: "https://example.org/pitwall-demo/gt3" }],
  },
  touring: {
    confidence: "low",
    values: {
      "tires.pressure_front": V(29.0, [28.0, 30.0], "Hot ≈ 33 psi"),
      "tires.pressure_rear": V(28.0, [27.0, 29.0], "Hot ≈ 33 psi"),
      "gearing.final_drive": R("≈ 50% of slider", "Top gear: no limiter"),
      "alignment.camber_front": V(-2.2, [-2.8, -1.8]),
      "alignment.camber_rear": V(-1.2, [-1.6, -0.8]),
      "alignment.toe_front": V(0.0, [-0.1, 0.1]),
      "alignment.toe_rear": V(-0.1, [-0.2, 0.0], "Toe-out for rotation"),
      "alignment.caster": V(5.5, [5.0, 6.5]),
      "arb.front": V(15, [10, 20]),
      "arb.rear": V(25, [18, 32]),
      "springs.front": R("≈ 50% of slider"),
      "springs.rear": R("≈ 55% of slider"),
      "springs.ride_height_front": R("3 clicks above min"),
      "springs.ride_height_rear": R("3 clicks above min"),
      "damping.rebound_front": V(9.0, [7.5, 10.5]),
      "damping.rebound_rear": V(9.5, [8.0, 11.0]),
      "damping.bump_front": V(5.5, [4.5, 6.5]),
      "damping.bump_rear": V(6.0, [5.0, 7.0]),
      "aero.front": R("≈ 50% of slider"),
      "aero.rear": R("≈ 50% of slider"),
      "brake.balance": V(55, [52, 58]),
      "brake.pressure": V(95, [90, 105]),
      "diff.accel_front": V(35, [25, 45], "FWD only"),
      "diff.decel_front": V(10, [0, 20], "FWD only"),
      "diff.accel_rear": V(45, [35, 55], "RWD only"),
      "diff.decel_rear": V(20, [10, 30], "RWD only"),
    },
    notes: ["Demo values", "FWD and RWD rows"],
    sources: [{ title: "Demo source D", url: "https://example.org/pitwall-demo/touring" }],
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
  return { category, unit_system: "imperial", settings, notes: d.notes, sources: d.sources, confidence: d.confidence };
}
