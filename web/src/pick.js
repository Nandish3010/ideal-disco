// Pure selectors for the read-only judge panels; every row is {id, ...doc} with Firestore Timestamps or ISO strings.
const ms = (v) => (v?.toMillis ? v.toMillis() : v ? new Date(v).getTime() || 0 : 0);
const newest = (rows, f) => [...rows].sort((a, b) => ms(f(b)) - ms(f(a)));

// First alert (rows already newest first) that has speech to play.
export const firstWithAudio = (rows) => rows.find((a) => a.audio_url) ?? null;

// The alert the "Sample alert" button plays when nothing is pinned: the PREPARE alert with speech and the longest queue
// (jam_m), newest among equals, else the newest alert with speech. rows: any order.
export const sampleAlert = (rows) =>
  newest(
    rows.filter((a) => a.stage === "PREPARE" && a.audio_url),
    (a) => a.created_at,
  ).sort((a, b) => (b.jam_m ?? 0) - (a.jam_m ?? 0))[0] ??
  firstWithAudio(newest(rows, (a) => a.created_at));

// Most recent handover brief written by a real model run (the offline stub does not count).
export const lastBrief = (rows) =>
  newest(
    rows.filter((b) => b.model && b.model !== "offline"),
    (b) => b.generated_at,
  )[0] ?? null;

// The hospital a run is bound for, by name (the roster name, as /hospital matches it).
export const destName = (run) => run?.destination?.name ?? null;

// "Last handover" for one hospital: the pinned brief when its run went to that hospital, else the newest model-written
// brief of a run that did. pinned: brief row | null; pinnedRun: its run row | null; hospital: roster name (falsy = any).
export function handover({ pinned, pinnedRun, briefs, runs, hospital }) {
  if (pinned && (!hospital || destName(pinnedRun) === hospital)) return pinned;
  const byId = new Map(runs.map((r) => [r.id, r]));
  return lastBrief(briefs.filter((b) => !hospital || destName(byId.get(b.id)) === hospital));
}

// Most recent run whose hospital routing was applied, or that shows a multi-step trace.
export const lastRouted = (runs) =>
  newest(
    runs.filter((r) => r.routing && (r.routing.applied === true || r.routing.trace?.length > 1)),
    (r) => r.routing.decided_at ?? r.started_at,
  )[0] ?? null;

// "Last routing decision": the pinned run when it has a routing, else the newest routed run.
export const routedRun = (pinnedRun, runs) => (pinnedRun?.routing ? pinnedRun : lastRouted(runs));

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
