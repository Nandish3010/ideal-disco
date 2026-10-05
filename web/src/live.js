import { useEffect, useState } from "react";
import { collection, collectionGroup, limit, onSnapshot, orderBy, query, where } from "firebase/firestore";
import { db } from "./firebase.js";

export const ACTIVE = ["en_route", "stale", "off_route"];

// Live junction docs for one corridor -> {docId: data}. Doc ids are `${corridor}_${id}`.
// ponytail: listens to the whole (small) collection and filters by prefix client-side.
export function useJunctions(corridor) {
  const [s, setS] = useState({});
  useEffect(() => {
    setS({});
    return onSnapshot(
      collection(db, "junctions"),
      (q) => setS(Object.fromEntries(q.docs.filter((d) => d.id.startsWith(`${corridor}_`)).map((d) => [d.id, d.data()]))),
      (e) => console.warn("junctions listener:", e.message),
    );
  }, [corridor]);
  return s;
}

// Live active runs for one corridor -> [{id, ...run}]. Equality + `in` only, so no composite index.
export function useActiveRuns(corridor) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    setRows([]);
    return onSnapshot(
      query(collection(db, "runs"), where("corridor", "==", corridor), where("state", "in", ACTIVE)),
      (q) => setRows(q.docs.map((d) => ({ id: d.id, ...d.data() }))),
      (e) => console.warn("runs listener:", e.message),
    );
  }, [corridor]);
  return rows;
}

const at = (a) => (a.created_at?.toMillis ? a.created_at.toMillis() : a.created_at ? new Date(a.created_at).getTime() : 0);
const newest = (rows) => rows.sort((a, b) => at(b) - at(a) || String(b.id).localeCompare(String(a.id), undefined, { numeric: true })).slice(0, 5);

// Latest 5 alerts -> {rows, mode}. Tries collectionGroup(alerts) ordered by created_at desc; that needs a
// collection-group index on created_at, so on error it falls back to reading runs/{id}/alerts for each active run.
export function useAlerts(runIds) {
  const [cg, setCg] = useState({ rows: [], failed: false });
  const [per, setPer] = useState({});
  useEffect(() => onSnapshot(
    query(collectionGroup(db, "alerts"), orderBy("created_at", "desc"), limit(5)),
    (q) => setCg({ rows: q.docs.map((d) => ({ id: d.id, run_id: d.ref.parent.parent?.id, ...d.data() })), failed: false }),
    (e) => { console.warn("alerts collectionGroup failed, using per-run reads:", e.code, e.message); setCg({ rows: [], failed: true }); },
  ), []);

  const key = runIds.join(",");
  useEffect(() => {
    setPer({});
    if (!cg.failed) return;
    const offs = runIds.map((id) => onSnapshot(
      collection(db, `runs/${id}/alerts`),
      (q) => setPer((p) => ({ ...p, [id]: q.docs.map((d) => ({ id: d.id, run_id: id, ...d.data() })) })),
      (e) => console.warn("alerts listener:", id, e.message),
    ));
    return () => offs.forEach((f) => f());
  }, [cg.failed, key]);

  return cg.failed ? { rows: newest(Object.values(per).flat()), mode: "per-run" } : { rows: cg.rows, mode: "group" };
}
