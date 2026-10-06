// In-memory stand-in for firebase/firestore: onSnapshot answers synchronously from FIX, keyed by "a/b/c" path.
// Collections map to arrays of {id, run_id?, ...fields}; docs map to a plain object (or undefined = missing).
const NOW = Date.now();
const at = (ms) => ({ toMillis: () => ms, toDate: () => new Date(ms) });

export const FIX = {
  incidents: [
    {
      id: "INC-4BC6E7",
      type: "medical",
      state: "open",
      severity_note: "chest pain",
      created_at: at(NOW - 60_000),
    },
    {
      id: "INC-A1B2C3",
      type: "fire",
      state: "closed",
      severity_note: "kitchen",
      created_at: at(NOW - 3_600_000),
    },
  ],
  runs: [
    {
      id: "r1",
      vehicle_plate: "KA01AB1234",
      vehicle_type: "ambulance",
      confirmed_tier: "critical",
      state: "en_route",
      corridor: "blr",
      incident_id: "INC-4BC6E7",
      eta_hospital_s: 600,
      eta_s: 90,
      started_at: at(NOW - 120_000),
      last_tick_at: at(NOW),
      destination: { name: "Jayadeva Institute of Cardiovascular Sciences" },
    },
    {
      id: "r2",
      vehicle_plate: "KA01AB4321",
      vehicle_type: "ambulance",
      confirmed_tier: "urgent",
      state: "en_route",
      corridor: "blr",
      incident_id: "INC-A1B2C3",
      eta_hospital_s: 900,
      eta_s: 200,
      started_at: at(NOW - 60_000),
      last_tick_at: at(NOW),
      destination: { name: "Jayadeva Institute of Cardiovascular Sciences" },
    },
  ],
  "runs/r1": {
    vehicle_plate: "KA01AB1234",
    vehicle_type: "ambulance",
    confirmed_tier: "critical",
    state: "en_route",
    incident_id: "INC-4BC6E7",
    eta_hospital_s: 600,
    destination: { name: "Jayadeva Institute of Cardiovascular Sciences" },
  },
  "runs/r1/log": [
    {
      id: "1",
      kind: "voice",
      t: at(NOW),
      confirmed: true,
      transcript_en: "chest pain, BP 85 over 50",
      fields: { vitals: { sbp: 85 } },
      interventions: [{ name: "Aspirin", dose: "300 mg", kind: "drug" }],
    },
  ],
  "runs/r1/alerts": [
    {
      id: "1",
      junction_id: "blr_j3",
      stage: "STOP",
      text: "Ambulance coming, critical case.",
      created_at: at(NOW - 1000),
      eta_s: 90,
    },
  ],
  alerts: [
    {
      id: "1",
      run_id: "r1",
      junction_id: "blr_j3",
      stage: "STOP",
      text: "Ambulance coming, critical case.",
      created_at: at(NOW - 1000),
      eta_s: 90,
      exit_move: "left",
      approach: "south",
    },
  ],
  briefs: [
    {
      id: "r1",
      generated_at: at(NOW),
      summary: "Chest pain, hypotensive.",
      atmist: { age: "58" },
      checklist: ["Cath lab"],
      disclaimer: "A clinician confirms.",
    },
  ],
  "briefs/r1": {
    generated_at: at(NOW),
    summary: "Chest pain, hypotensive.",
    atmist: { age: "58" },
    checklist: ["Cath lab"],
  },
  duty: [{ id: "blr_j3", name: "Ravi" }],
  "duty/blr_j3": { on: true, since: at(NOW) },
  junctions: [{ id: "blr_j3", phase: { approach: "south", until: at(NOW + 60_000) } }],
  reports: [{ id: "r1", minutes_saved: 3.2, baseline_s: 600, actual_s: 400, junctions_cleared: 3 }],
};

const snap = (rows) => ({
  docs: rows.map(({ id, run_id, ...f }) => ({
    id,
    data: () => f,
    ref: { parent: { parent: { id: run_id ?? "r1" } } },
  })),
});

const subs = new Set(); // live listeners: [path, isCollection, ok]
const deliver = (path, col, ok) => {
  const v = FIX[path];
  if (col) ok(snap(v ?? []));
  else ok({ exists: () => v != null, data: () => v });
};
// Replace a path's data and tell every listener on it (a "new alert arrives" in a test).
export const push = (path, value) => {
  FIX[path] = value;
  subs.forEach(([p, col, ok]) => p === path && deliver(p, col, ok));
};

export const firestore = {
  collection: (_db, ...p) => ({ path: p.join("/"), col: true }),
  collectionGroup: (_db, name) => ({ path: name, col: true }),
  doc: (_db, ...p) => ({ path: p.join("/") }),
  query: (ref) => ref,
  where: () => 0,
  orderBy: () => 0,
  limit: () => 0,
  onSnapshot: (ref, ok) => {
    const sub = [ref.path, !!ref.col, ok];
    subs.add(sub);
    deliver(...sub);
    return () => subs.delete(sub);
  },
  getDocs: async (ref) => snap(FIX[ref.path] ?? []),
};
