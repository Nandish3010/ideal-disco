// Pure client-side replay maths: no React, no network. Scenario in, with-vs-without numbers out.
// jamMetres / clearSeconds / blendedEta / stage mirror api/leadtime.py; keep them in step.

export function jamMetres(intervals) {
  let total = 0;
  for (const iv of [...intervals].sort((a, b) => b.to_m - a.to_m)) {
    const len = iv.to_m - iv.from_m;
    if (iv.speed === "TRAFFIC_JAM") total += len;
    else if (iv.speed === "SLOW") total += 0.5 * len;
    else break;
  }
  return total;
}

const DRAIN_MPS = 2.0;
export const clearSeconds = (jam, reaction = 20, rate = DRAIN_MPS) => reaction + jam / rate;
export const blendedEta = (routesEta, distance, observed) =>
  0.5 * routesEta + 0.5 * (distance / Math.max(observed, 3));
export function stage(eta, clear, buffer = 15) {
  if (eta <= 30) return "STOP";
  if (eta <= clear + buffer) return "PREPARE";
  return null;
}

// ---- recorded spans: {junction: [{ts, approach?, intervals}]}, snapshot in force at scenario time t ----
export function snapshotAt(snaps, t) {
  if (!snaps?.length) return null;
  const t0 = Date.parse(snaps[0].ts);
  return snaps.findLast((s) => (Date.parse(s.ts) - t0) / 1000 <= t) ?? snaps[0];
}
export const spansAt = (rec, t) =>
  Object.fromEntries(
    Object.entries(rec ?? {}).map(([k, snaps]) => [k, snapshotAt(snaps, t).intervals]),
  );

// A snapshot with `approach` only counts for vehicles on that approach.
function jamAt(sc, junction, approach, t) {
  const s = snapshotAt(sc.recorded_spans?.[`${sc.corridor}_${junction}`], t);
  if (!s || (s.approach && approach && s.approach !== approach)) return 0;
  return jamMetres(s.intervals);
}

// ---- when does each vehicle reach each junction? closest point of its trace to the junction (< 100 m) ----
const rad = Math.PI / 180;
function passes(v, corridor) {
  const out = [];
  for (const j of corridor.junctions) {
    const kx = Math.cos(j.lat * rad) * 111195,
      ky = 111195;
    let best = null;
    for (let i = 0; i + 1 < v.ticks.length; i++) {
      const a = v.ticks[i],
        b = v.ticks[i + 1];
      const ax = (a.lng - j.lng) * kx,
        ay = (a.lat - j.lat) * ky;
      const dx = (b.lng - a.lng) * kx,
        dy = (b.lat - a.lat) * ky;
      const f = Math.min(1, Math.max(0, -(ax * dx + ay * dy) / (dx * dx + dy * dy || 1)));
      const d = Math.hypot(ax + f * dx, ay + f * dy);
      if (!best || d < best.d) best = { d, t: a.t + f * (b.t - a.t) };
    }
    if (best && best.d < 100)
      out.push({
        junction: j.id,
        approach: v.approaches?.[j.id] ?? null,
        t: best.t,
        cycle_s: j.cycle_s ?? 120,
      });
  }
  return out.sort((a, b) => a.t - b.t);
}

const base = (v, corridor) => ({
  plate: v.plate,
  start_s: v.start_offset_s ?? 0,
  duration_s: v.ticks.at(-1).t,
  passes: passes(v, corridor),
});

// "Today": the same baseline as api/report.py. At every junction the vehicle passes it stops for the remaining red
// (arrival at mid-red = cycle_s / 4) plus the recorded queue ahead draining at 2.0 m/s (jam_m / 2.0). Deterministic.
export function simulateWithout(sc, corridor) {
  return sc.vehicles.map((v) => {
    const b = base(v, corridor);
    const stops = b.passes.map((p) => {
      const jam_m = jamAt(sc, p.junction, p.approach, b.start_s + p.t);
      const red_s = p.cycle_s / 4,
        drain_s = jam_m / DRAIN_MPS;
      return { junction: p.junction, t: p.t, wait_s: red_s + drain_s, red_s, drain_s, jam_m };
    });
    return { ...b, stops, without_s: b.duration_s + stops.reduce((s, x) => s + x.wait_s, 0) };
  });
}

// "With corridor": same trace, no stops. Only sequencing delays remain: at a junction, vehicles on different
// approaches arriving within 30 s go in tier order, 12 s apart (api/priority.py); same approach shares the green.
const RANK = [
  "fire_with_trapped",
  "ambulance_critical",
  "fire",
  "ambulance_urgent",
  "police_with_incident",
  "ambulance_stable",
];
const GAP_S = 12,
  WINDOW_S = 30;
const rank = (v) => {
  const i = RANK.indexOf(v.tier && RANK.includes(v.tier) ? v.tier : `${v.type}_${v.tier}`);
  return i < 0 ? RANK.length : i;
};
const label = (v, other, lower) =>
  v.type === other.type ? v.plate : lower ? v.type : v.type[0].toUpperCase() + v.type.slice(1);

export function simulateWith(sc, corridor) {
  const all = sc.vehicles.map((v) => ({ v, ...base(v, corridor) }));
  return all.map((x) => {
    const offsets = [];
    for (const p of x.passes) {
      const mine = x.start_s + p.t;
      const ahead = all
        .filter((y) => y !== x)
        .flatMap((y) => {
          const q = y.passes.find((q) => q.junction === p.junction);
          const when = q && y.start_s + q.t;
          const first =
            q &&
            q.approach !== p.approach &&
            Math.abs(when - mine) <= WINDOW_S &&
            (rank(y.v) < rank(x.v) || (rank(y.v) === rank(x.v) && when < mine));
          return first ? [{ y, approach: q.approach }] : [];
        })
        .sort((a, b) => rank(a.y.v) - rank(b.y.v));
      if (!ahead.length) continue;
      const offset_s = GAP_S * new Set(ahead.map((a) => a.approach)).size;
      offsets.push({
        junction: p.junction,
        t: p.t,
        offset_s,
        text: `${label(ahead[0].y.v, x.v)} first, ${label(x.v, ahead[0].y.v, true)} ${offset_s} s later`,
      });
    }
    const { v, ...rest } = x;
    return { ...rest, offsets, with_s: x.duration_s + offsets.reduce((s, o) => s + o.offset_s, 0) };
  });
}

// ---- both lanes together; holds are {junction, t (trace time), d (seconds), at (scenario time)} ----
function schedule(v, list, key) {
  let shift = 0;
  return list.map((h) => {
    const x = { junction: h.junction, t: h.t, d: h[key], at: v.start_offset_s + h.t + shift };
    shift += x.d;
    return x;
  });
}

export function simulate(sc, corridor) {
  const wo = simulateWithout(sc, corridor),
    w = simulateWith(sc, corridor);
  const vehicles = sc.vehicles.map((v, i) => ({
    ...wo[i],
    offsets: w[i].offsets,
    with_s: w[i].with_s,
    saved_s: wo[i].without_s - w[i].with_s,
    id: v.run_id,
    type: v.type,
    tier: v.tier,
    ticks: v.ticks,
    passes: wo[i].passes.map((p) => {
      const jam_m = jamAt(sc, p.junction, p.approach, wo[i].start_s + p.t);
      return { ...p, jam_m, clear_s: clearSeconds(jam_m) };
    }),
    holdsWithout: schedule(v, wo[i].stops, "wait_s"),
    holdsWith: schedule(v, w[i].offsets, "offset_s"),
  }));
  return {
    vehicles,
    saved_s: vehicles.reduce((s, v) => s + v.saved_s, 0),
    end_s: Math.max(...vehicles.map((v) => v.start_s + v.without_s)),
    sequencing: vehicles.flatMap((v) => v.offsets.map((o) => ({ ...o, at: v.start_s + o.t }))),
  };
}

// Where is vehicle v at scenario time T given its holds? {lat, lng, started, hold (current or null), delay (s lost so far)}
export function at(v, holds, T) {
  let shift = 0,
    hold = null;
  for (const h of holds) {
    if (T < h.at) break;
    if (T < h.at + h.d) {
      hold = h;
      break;
    }
    shift += h.d;
  }
  const local = Math.min(Math.max(hold ? hold.t : T - v.start_s - shift, 0), v.duration_s);
  const i = Math.max(
    0,
    v.ticks.findLastIndex((k) => k.t <= local),
  );
  const a = v.ticks[i],
    b = v.ticks[i + 1] ?? a;
  const f = b.t > a.t ? (local - a.t) / (b.t - a.t) : 0;
  return {
    lat: a.lat + (b.lat - a.lat) * f,
    lng: a.lng + (b.lng - a.lng) * f,
    started: T >= v.start_s,
    local,
    hold,
    delay: shift + (hold ? T - hold.at : 0),
  };
}

// Minutes saved so far: delay accrued Today minus delay accrued with the corridor (ends at saved_s).
export const savedAt = (vehicles, T) =>
  vehicles.reduce(
    (s, v) => s + Math.max(0, at(v, v.holdsWithout, T).delay - at(v, v.holdsWith, T).delay),
    0,
  );
