// Pure helpers for /story (the last run as a timeline) and the on-duty presence line. Rows are {id, ...doc}; times are Firestore Timestamps or ISO strings.
import { rel } from "./ui.jsx";

export const ms = (v) => (v?.toMillis ? v.toMillis() : v ? new Date(v).getTime() || 0 : 0);
const hhmm = (v) =>
  new Date(ms(v)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });

// "Constable Rao · On duty since 09:12 · last ACK 2 min ago (1.7 s)"; grey "no constable" when nobody is on duty.
// alerts: the junction's alerts (any run).
export function presence(duty, alerts, now) {
  if (!duty || duty.on === false) return { on: false, text: "no constable" };
  const a = alerts.filter((x) => x.acked_at).sort((x, y) => ms(y.acked_at) - ms(x.acked_at))[0];
  const ack = a
    ? `last ACK ${rel(a.acked_at, now)}${a.ack_latency_s != null ? ` (${Number(a.ack_latency_s).toFixed(1)} s)` : ""}`
    : "no ACK yet";
  const since = duty.since ? `On duty since ${hhmm(duty.since)}` : "On duty";
  return { on: true, text: [duty.name, since, ack].filter(Boolean).join(" · ") };
}

// cands: [{run, alerts: n, brief: bool}] -> the run /story tells. Newest finished ambulance run with alerts and a brief,
// else the newest ambulance run with alerts, else the newest run of any kind with alerts.
export function chooseRun(cands) {
  const newest = [...cands].sort((a, b) => ms(b.run.started_at) - ms(a.run.started_at));
  const amb = newest.filter((c) => c.run.vehicle_type === "ambulance" && c.alerts > 0);
  return (amb.find((c) => c.brief) ?? amb[0] ?? newest.find((c) => c.alerts > 0))?.run ?? null;
}

const ORDER = ["start", "log", "route", "alert", "phase", "brief", "arrival", "report", "aar"];

// Merge everything one run left behind into one list, oldest first. Each item: {id, kind, t, jid?, approach?, ...}.
// d: {run, log, alerts, audit, junctions: {docId: doc}, brief, report, aar}
export function buildTimeline({
  run,
  log = [],
  alerts = [],
  audit = [],
  junctions = {},
  brief,
  report,
  aar,
}) {
  const t0 = ms(run.started_at);
  const at = (v) => ms(v) || t0;
  const items = [{ id: "start", kind: "start", t: t0, run }];
  log.forEach((e) => items.push({ id: `log-${e.id}`, kind: "log", t: at(e.t), e }));
  if (run.confirmed_tier || run.routing)
    items.push({
      id: "route",
      kind: "route",
      t: at(run.routing?.decided_at ?? log[0]?.t),
      tier: run.confirmed_tier,
      routing: run.routing,
    });
  alerts.forEach((a) =>
    items.push({
      id: `alert-${a.id}`,
      kind: "alert",
      t: at(a.created_at),
      jid: a.junction_id,
      approach: a.approach,
      a,
    }),
  );
  const seen = new Set();
  audit
    .filter((x) => x.action === "preempt_requested" && x.run_id === run.id)
    .sort((a, b) => ms(a.at) - ms(b.at))
    .forEach((x) => {
      const k = x.junction_id + JSON.stringify(x.sequence ?? []);
      if (seen.has(k)) return;
      seen.add(k);
      const ph = junctions[x.junction_id]?.phase;
      items.push({
        id: `phase-${seen.size}`,
        kind: "phase",
        t: at(x.at),
        jid: x.junction_id,
        approach: x.approach,
        sequence: x.sequence,
        rationale: ph?.run_ids?.includes(run.id) ? ph.rationale : null,
      });
    });
  if (brief) items.push({ id: "brief", kind: "brief", t: at(brief.generated_at), brief });
  const done = ["arrived", "ended"].includes(run.state);
  const last = Math.max(...items.map((i) => i.t));
  const end = Math.max(last, ms(run.last_tick_at));
  if (done) items.push({ id: "arrival", kind: "arrival", t: end, run });
  if (report) items.push({ id: "report", kind: "report", t: end + 1, report });
  if (aar) items.push({ id: "aar", kind: "aar", t: Math.max(end + 2, ms(aar.generated_at)), aar });
  return items.sort((a, b) => a.t - b.t || ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
}

const FAR = Date.UTC(2100, 0, 1);
// What the sticky map shows for the current item: its junction green on its approach, or the vehicle at the run's last tick on arrival
// (`ticks` is a rolling window, so its first entry is not where the run started).
export function mapState(item, run) {
  if (!item) return {};
  if (item.jid)
    return { phases: { [item.jid]: { approach: item.approach, until: FAR } }, vehicles: [] };
  const k = item.kind === "arrival" ? run.ticks?.at(-1) : null;
  return {
    phases: {},
    vehicles: k ? [{ id: run.id, type: run.vehicle_type, lat: k.lat, lng: k.lng }] : [],
  };
}
