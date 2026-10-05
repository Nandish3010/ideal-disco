import { useEffect, useState } from "react";
import { collection, doc, onSnapshot } from "firebase/firestore";
import { db } from "./firebase.js";

// localStorage can throw (private mode); fall back to memory-less defaults.
export const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* ignore */ } },
};

export function deviceId() {
  let id = store.get("device_id");
  if (!id) {
    // randomUUID needs a secure context; LAN http dev falls back
    id = crypto.randomUUID?.() ?? "dev-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
    store.set("device_id", id);
  }
  return id;
}

// Live Firestore doc -> {data, loading, error, missing}
export function useDoc(path) {
  const [s, setS] = useState({ loading: !!path });
  useEffect(() => {
    if (!path) { setS({}); return; }
    setS({ loading: true });
    return onSnapshot(
      doc(db, path),
      (d) => setS(d.exists() ? { data: d.data() } : { missing: true }),
      (e) => setS({ error: e.message }),
    );
  }, [path]);
  return s;
}

// Live runs/{id}/log -> {rows, error}. Sorted client-side by `n` (field, else doc id) so a doc missing the field is never dropped.
export function useLog(runId) {
  const [s, setS] = useState({});
  useEffect(() => {
    setS({});
    if (!runId) return;
    return onSnapshot(
      collection(db, `runs/${runId}/log`),
      (q) => setS({ rows: q.docs.map((d) => ({ id: d.id, ...d.data() })).sort((a, b) => (a.n ?? a.id) - (b.n ?? b.id)) }),
      (e) => setS({ error: e.message }),
    );
  }, [runId]);
  return s;
}

export const when = (v) => (v?.toDate ? v.toDate() : v ? new Date(v) : null)?.toLocaleTimeString() ?? "";

export const Err = ({ e, retry }) => e ? <p className="card bad">Error: {e.message}{e.status ? ` (${e.status})` : ""}{retry && <> <button onClick={retry}>Retry</button></>}</p> : null;

// ---- shared UI states (loading / error / offline / stale) ----
export function useNow(step = 1000) {
  const [n, setN] = useState(Date.now());
  useEffect(() => { const id = setInterval(() => setN(Date.now()), step); return () => clearInterval(id); }, [step]);
  return n;
}

// Generic live listener -> {data, loading, error, retry}. subscribe(ok, bad) returns the unsubscribe fn.
// A Firestore listener error is terminal, so retry() re-subscribes.
export function useListen(subscribe, deps) {
  const [s, setS] = useState({ loading: true });
  const [n, setN] = useState(0);
  useEffect(() => {
    setS({ loading: true });
    return subscribe((data) => setS({ data }), (e) => setS({ error: e.message || String(e) }));
  }, [...deps, n]); // eslint-disable-line react-hooks/exhaustive-deps
  return { ...s, retry: () => setN((x) => x + 1) };
}

export const ErrCard = ({ what, error, retry }) => error
  ? <div className="card bad" role="alert">Could not load {what}: {error} <button onClick={retry}>Retry</button></div> : null;

// Slim top banner while the browser is offline; the page stays usable.
export function Offline() {
  const [on, setOn] = useState(navigator.onLine);
  useEffect(() => {
    const up = () => setOn(true), down = () => setOn(false);
    addEventListener("online", up); addEventListener("offline", down);
    return () => { removeEventListener("online", up); removeEventListener("offline", down); };
  }, []);
  return on ? null : <div className="offline" role="status">Reconnecting…</div>;
}

const t = (v) => (v?.toMillis ? v.toMillis() : v ? new Date(v).getTime() : 0);
export const rel = (v, now) => {
  if (!t(v)) return "";
  const s = Math.max(0, Math.round((now - t(v)) / 1000));
  return s < 5 ? "just now" : s < 60 ? `${s} s ago` : s < 3600 ? `${Math.floor(s / 60)} min ago` : s < 86400 ? `${Math.floor(s / 3600)} h ago` : `${Math.floor(s / 86400)} d ago`;
};

// Run state badge: STALE (grey) / OFF ROUTE (amber) / ARRIVED (green) / EN ROUTE.
export const StateBadge = ({ run, now }) => {
  const s = run.state, tick = t(run.last_tick_at);
  const label = s === "stale" ? `STALE · last tick ${tick ? Math.max(0, Math.round((now - tick) / 1000)) : "?"} s ago`
    : s === "off_route" ? "OFF ROUTE" : s === "arrived" ? "ARRIVED" : s === "en_route" ? "EN ROUTE" : s ?? "—";
  return <span className={`cb st-${s}`}>{label}</span>;
};
