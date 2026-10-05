import { useEffect, useState } from "react";
import { collection, limit, onSnapshot, orderBy, query } from "firebase/firestore";
import { db } from "../firebase.js";
import { api } from "../api.js";
import { Err, when } from "../ui.jsx";

function Recent() {
  const [s, setS] = useState({ loading: true });
  useEffect(() => onSnapshot(
    query(collection(db, "incidents"), orderBy("created_at", "desc"), limit(10)),
    (q) => setS({ rows: q.docs.map((d) => ({ id: d.id, ...d.data() })) }),
    (e) => setS({ error: e.message }),
  ), []);
  if (s.loading) return <p className="muted">Loading incidents…</p>;
  if (s.error) return <p className="card bad">Could not load incidents: {s.error}</p>;
  if (!s.rows.length) return <p className="muted">No incidents yet.</p>;
  return (
    <ul className="list">
      {s.rows.map((r) => (
        <li key={r.id}><b>{r.id}</b> <span className="pill">{r.type}</span> <span className="pill">{r.state}</span>
          <div className="muted">{when(r.created_at)} {r.severity_note}</div></li>
      ))}
    </ul>
  );
}

export default function Dispatch() {
  const [type, setType] = useState("medical");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [id, setId] = useState(null);
  const [copied, setCopied] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setErr(null); setCopied(false);
    try { setId((await api("/incidents", { type, severity_note: note })).incident_id); }
    catch (x) { setErr(x); }
    setBusy(false);
  }
  const copy = async () => {
    try { await navigator.clipboard.writeText(id); setCopied(true); } catch { setCopied(false); }
  };

  return (
    <>
      <form className="card" onSubmit={submit}>
        <label>Incident type
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="medical">medical</option><option value="fire">fire</option><option value="police">police</option>
          </select>
        </label>
        <label>Severity note
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="chest pain, adult" />
        </label>
        <button className="primary" disabled={busy}>{busy ? "Issuing…" : "Issue incident ID"}</button>
      </form>
      <Err e={err} />
      {id && (
        <div className="card good">
          <div className="muted">Incident ID</div>
          <div className="big">{id}</div>
          <button onClick={copy}>{copied ? "Copied" : "Copy"}</button>
        </div>
      )}
      <h2>Last 10 incidents</h2>
      <Recent />
    </>
  );
}
