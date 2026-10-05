// Pure formatters for the routing trace card and the junction sequence line.
export const mmss = (s) => {
  s = Math.round(s);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

// One trace entry as a line: the backend's `text` when present, else tool(args) → result, else the fallback marker.
export function traceLine(e) {
  if (e.text) return e.text.replace("->", "→");
  if (e.tool) {
    const args = Object.values(e.args ?? {}).map((v) =>
      typeof v === "object" ? JSON.stringify(v) : v,
    );
    return `called ${e.tool}(${args.join(", ")}) → ${e.result ?? "—"}`;
  }
  return e.fallback ? `fallback used (${e.fallback})` : JSON.stringify(e);
}

const KIND = { fire: "Fire engine", police: "Police", ambulance: "Ambulance" };
const who = (r, id) =>
  r
    ? [
        KIND[r.vehicle_type] ?? r.vehicle_type,
        r.vehicle_type === "ambulance" && (r.confirmed_tier ?? r.acuity_tier),
      ]
        .filter(Boolean)
        .join(" ")
    : id;

// "Fire engine → +0 s · Ambulance critical → +12 s · Ambulance urgent → +12 s (shared)"; "" below two vehicles.
// A later vehicle with the same offset as an earlier one is marked shared. runs: array of {id, vehicle_type, ...}.
export function seqLine(sequence, runs = []) {
  if ((sequence?.length ?? 0) < 2) return "";
  return sequence
    .map((s, i) => {
      const shared = sequence.slice(0, i).some((p) => p.offset_s === s.offset_s);
      const r = runs.find((x) => x.id === s.run_id);
      return `${who(r, s.run_id)} → +${s.offset_s} s${shared ? " (shared)" : ""}`;
    })
    .join(" · ");
}

// "Fire engine · trapped persons", "Ambulance · critical". Raw enums (fire_with_trapped, police_with_incident) never reach the screen.
const TIER = { fire_with_trapped: "trapped persons", police_with_incident: "incident" };
export function vehicleLabel(type, tier) {
  const kind = KIND[type] ?? type ?? "Vehicle";
  const t = tier && tier !== type ? (TIER[tier] ?? String(tier).replaceAll("_", " ")) : null;
  return t ? `${kind} · ${t}` : kind;
}

// "2 min" / "90 s" for a number of seconds.
export const dur = (s) => (s % 60 === 0 ? `${s / 60} min` : `${s} s`);

const COP_KIND = {
  delay: "delay",
  cleared: "clear",
  cannot_clear: "cannot clear",
  other: "update",
};
// The cop's report on an alert (alerts/{n}.cop_note) as one line for the vehicle: "Cop at J3: bus stalled, +2 min".
export function copNoteText(note, junctionId) {
  if (!note) return "";
  const j = String(junctionId).split("_").pop().toUpperCase();
  const said = ["delay", "other"].includes(note.kind)
    ? note.reason || COP_KIND[note.kind]
    : [COP_KIND[note.kind], note.reason && `(${note.reason})`].filter(Boolean).join(" ");
  const more = note.kind === "delay" && note.extra_seconds ? `, +${dur(note.extra_seconds)}` : "";
  return `Cop at ${j}: ${said}${more}`;
}

// The alert a vehicle is on now: the newest one at its next junction, else the newest at all.
export function currentAlert(alerts, nextJunction) {
  const at = (a) => a.created_at?.toMillis?.() ?? 0;
  const mine = alerts.filter((a) => !nextJunction || a.junction_id === nextJunction);
  return [...(mine.length ? mine : alerts)].sort((a, b) => at(b) - at(a))[0];
}
