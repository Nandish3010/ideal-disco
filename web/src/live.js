import { useEffect, useState } from "react";
import { collection, collectionGroup, limit, onSnapshot, orderBy, query, where } from "firebase/firestore";
import { db } from "./firebase.js";
import { useListen } from "./ui.jsx";

// arrived stays listed (ARRIVED badge) for a while; ended runs leave the query
export const ACTIVE = ["en_route", "stale", "off_route", "arrived"];
export const LIVE = ["en_route", "stale", "off_route"]; // still moving: eligible for escalation
const ARRIVED_KEEP_MS = 10 * 60 * 1000;
const tick = (r) => (r.last_tick_at?.toMillis ? r.last_tick_at.toMillis() : r.last_tick_at ? new Date(r.last_tick_at).getTime() : 0);

// Live junction docs for one corridor -> {docId: data}. Doc ids are `${corridor}_${id}`.
// ponytail: listens to the whole (small) collection and filters by prefix client-side.
export function useJunctions(corridor) {
  const s = useListen((ok, bad) => onSnapshot(
    collection(db, "junctions"),
    (q) => ok(Object.fromEntries(q.docs.filter((d) => d.id.startsWith(`${corridor}_`)).map((d) => [d.id, d.data()]))),
    (e) => { console.warn("junctions listener:", e.message); bad(e); },
  ), [corridor]);
  return { ...s, data: s.data ?? {} };
}

// Live active runs for one corridor -> {data: [{id, ...run}], loading, error, retry}. Equality + `in` only, so no composite index.
export function useActiveRuns(corridor) {
  const s = useListen((ok, bad) => onSnapshot(
    query(collection(db, "runs"), where("corridor", "==", corridor), where("state", "in", ACTIVE)),
    (q) => ok(q.docs.map((d) => ({ id: d.id, ...d.data() })).filter((r) => r.state !== "arrived" || Date.now() - tick(r) < ARRIVED_KEEP_MS)),
    (e) => { console.warn("runs listener:", e.message); bad(e); },
  ), [corridor]);
  return { ...s, data: s.data ?? [] };
}

const at = (a) => (a.created_at?.toMillis ? a.created_at.toMillis() : a.created_at ? new Date(a.created_at).getTime() : 0);
const newest = (rows) => rows.sort((a, b) => at(b) - at(a) || String(b.id).localeCompare(String(a.id), undefined, { numeric: true })).slice(0, 5);

// Latest 5 alerts -> {rows, mode, loading, error, retry}. Tries collectionGroup(alerts) ordered by created_at desc; that needs a
// collection-group index on created_at, so on error it falls back to reading runs/{id}/alerts for each run.
export function useAlerts(runIds) {
  const [cg, setCg] = useState({ loading: true, rows: [] });
  const [per, setPer] = useState({});
  const [perErr, setPerErr] = useState(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    setCg({ loading: true, rows: [] });
    return onSnapshot(
      query(collectionGroup(db, "alerts"), orderBy("created_at", "desc"), limit(5)),
      (q) => setCg({ rows: q.docs.map((d) => ({ id: d.id, run_id: d.ref.parent.parent?.id, ...d.data() })), failed: false }),
      (e) => { console.warn("alerts collectionGroup failed, using per-run reads:", e.code, e.message); setCg({ rows: [], failed: true }); },
    );
  }, [n]);

  const key = runIds.join(",");
  useEffect(() => {
    setPer({}); setPerErr(null);
    if (!cg.failed) return;
    const offs = runIds.map((id) => onSnapshot(
      collection(db, `runs/${id}/alerts`),
      (q) => setPer((p) => ({ ...p, [id]: q.docs.map((d) => ({ id: d.id, run_id: id, ...d.data() })) })),
      (e) => { console.warn("alerts listener:", id, e.message); setPerErr(e.message); },
    ));
    return () => offs.forEach((f) => f());
  }, [cg.failed, key, n]);

  const retry = () => setN((x) => x + 1);
  return cg.failed
    ? { rows: newest(Object.values(per).flat()), mode: "per-run", loading: !perErr && runIds.some((id) => !per[id]), error: perErr, retry }
    : { rows: cg.rows, mode: "group", loading: !!cg.loading, retry };
}
