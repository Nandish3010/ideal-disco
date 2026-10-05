import { useEffect, useState } from "react";
import { doc, onSnapshot } from "firebase/firestore";
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

export const when = (v) => (v?.toDate ? v.toDate() : v ? new Date(v) : null)?.toLocaleTimeString() ?? "";

export const Err = ({ e }) => e ? <p className="card bad">Error: {e.message}{e.status ? ` (${e.status})` : ""}</p> : null;
