import { useState } from "react";
import { collection, limit, onSnapshot, orderBy, query } from "firebase/firestore";
import { db } from "../firebase.js";
import { api } from "../api.js";
import { typeLabel, within } from "../pick.js";
import { Err, ErrCard, Offline, rel, useListen, useNow, when } from "../ui.jsx";

function Recent() {
  const s = useListen(
    (ok, bad) =>
      onSnapshot(
        query(collection(db, "incidents"), orderBy("created_at", "desc"), limit(30)),
        (q) => ok(q.docs.map((d) => ({ id: d.id, ...d.data() }))),
        bad,
      ),
    [],
  );
  const now = useNow(10000);
  if (s.loading) return <p className="muted">Loading…</p>;
  if (s.error) return <ErrCard what="incidents" error={s.error} retry={s.retry} />;
  const rows = within(s.data, now);
  if (!rows.length) return <p className="muted">No incidents in the last 24 h</p>;
  return (
    <ul className="list">
      {rows.map((r) => (
        <li key={r.id}>
          <b>{r.id}</b> <span className="pill">{typeLabel(r.type)}</span>{" "}
          <span className="pill">{r.state}</span>
          <div className="muted">
            {rel(r.created_at, now) || "time pending"} · {when(r.created_at)} {r.severity_note}
          </div>
        </li>
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

  async function submit(e, body = { type, severity_note: note }) {
    e?.preventDefault();
    setBusy(true);
    setErr(null);
    setCopied(false);
    try {
      setId((await api("/incidents", body)).incident_id);
    } catch (x) {
      setErr(x);
    }
    setBusy(false);
  }
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <>
      <Offline />
      <form className="card" onSubmit={submit}>
        <label>
          Incident type
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="medical">medical</option>
            <option value="fire">fire</option>
            <option value="police">police</option>
          </select>
        </label>
        <label>
          Severity note
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="chest pain, adult"
          />
        </label>
        <button className="primary" disabled={busy}>
          {busy ? "Issuing…" : "Issue incident ID"}
        </button>
      </form>
      <button
        type="button"
        disabled={busy}
        onClick={() =>
          submit(null, { type: "medical", severity_note: "Demo: chest pain, Silk Board" })
        }
      >
        Seed demo incident
      </button>
      <Err e={err} retry={submit} />
      {id && (
        <div className="card good" role="status">
          <div className="muted">Incident ID</div>
          <div className="big">{id}</div>
          <button onClick={copy}>{copied ? "Copied" : "Copy"}</button>
        </div>
      )}
      <h2>Incidents, last 24 h</h2>
      <Recent />
    </>
  );
}
