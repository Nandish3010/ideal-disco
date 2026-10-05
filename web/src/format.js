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
