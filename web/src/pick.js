// Pure selectors for the read-only judge panels; every row is {id, ...doc} with Firestore Timestamps or ISO strings.
const ms = (v) => (v?.toMillis ? v.toMillis() : v ? new Date(v).getTime() || 0 : 0);
const newest = (rows, f) => [...rows].sort((a, b) => ms(f(b)) - ms(f(a)));

// First alert (rows already newest first) that has speech to play.
export const firstWithAudio = (rows) => rows.find((a) => a.audio_url) ?? null;

// Most recent handover brief written by a real model run (the offline stub does not count).
export const lastBrief = (rows) =>
  newest(
    rows.filter((b) => b.model && b.model !== "offline"),
    (b) => b.generated_at,
  )[0] ?? null;

// Most recent run whose hospital routing was applied, or that shows a multi-step trace.
export const lastRouted = (runs) =>
  newest(
    runs.filter((r) => r.routing && (r.routing.applied === true || r.routing.trace?.length > 1)),
    (r) => r.routing.decided_at ?? r.started_at,
  )[0] ?? null;

export const DAY_MS = 24 * 3600 * 1000;
export const within = (rows, now, span = DAY_MS) =>
  rows.filter((r) => now - ms(r.created_at) < span && ms(r.created_at) > 0);

// medical / fire / police; anything else (cardiac, trauma...) is medical.
export const typeLabel = (t) => (t === "fire" || t === "police" ? t : "medical");

export const latestOpen = (incidents) =>
  newest(
    incidents.filter((i) => i.state === "open"),
    (i) => i.created_at,
  )[0] ?? null;

// Report-card rows: only reports that say how the baseline was measured.
export const withMethod = (reports) => reports.filter((r) => r.method);
