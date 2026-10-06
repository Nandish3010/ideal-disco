import { useState } from "react";
import { collection, limit, onSnapshot, orderBy, query } from "firebase/firestore";
import { db } from "../firebase.js";
import { api } from "../api.js";
import { typeLabel, within } from "../pick.js";
import { Err, ErrCard, Field, Offline, rel, useListen, useNow, when } from "../ui.jsx";
import { t } from "../i18n/index.js";

function Recent({ showClosed }) {
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
  if (s.loading) return <p className="muted">{t("common.loading")}</p>;
  if (s.error) return <ErrCard what={t("what.incidents")} error={s.error} retry={s.retry} />;
  const rows = within(s.data, now).filter((r) => showClosed || r.state !== "closed");
  if (!rows.length)
    return <p className="muted">{showClosed ? t("dispatch.none") : t("dispatch.none_open")}</p>;
  return (
    <ul className="list">
      {rows.map((r) => (
        <li key={r.id}>
          <b>{r.id}</b> <span className="pill">{typeLabel(r.type)}</span>{" "}
          <span className="pill">{r.state}</span>
          <div className="muted">
            {rel(r.created_at, now) || t("dispatch.time_pending")} · {when(r.created_at)}{" "}
            {r.severity_note}
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
  const [showClosed, setShowClosed] = useState(false);

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
        <Field label={t("dispatch.type")}>
          <select value={type} onChange={(e) => setType(e.target.value)} autoFocus>
            {["medical", "fire", "police"].map((k) => (
              <option key={k} value={k}>
                {t(`dispatch.t_${k}`)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("dispatch.note")} hint={t("dispatch.note_hint")}>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t("dispatch.note_ph")}
            maxLength={200}
            enterKeyHint="go"
            autoComplete="off"
          />
        </Field>
        <button className="primary" disabled={busy}>
          {busy ? t("dispatch.issuing") : t("dispatch.issue")}
        </button>
        <Err e={err} retry={submit} />
      </form>
      <button
        type="button"
        disabled={busy}
        onClick={() =>
          submit(null, { type: "medical", severity_note: "Demo: chest pain, Silk Board" })
        }
      >
        {t("dispatch.seed")}
      </button>
      {id && (
        <div className="card good" role="status">
          <div className="muted">{t("dispatch.id")}</div>
          <div className="big">{id}</div>
          <button onClick={copy}>{copied ? t("dispatch.copied") : t("dispatch.copy")}</button>
        </div>
      )}
      <h2>{t("dispatch.recent_h")}</h2>
      <button type="button" aria-pressed={showClosed} onClick={() => setShowClosed(!showClosed)}>
        {showClosed ? t("dispatch.hide_closed") : t("dispatch.show_closed")}
      </button>
      <Recent showClosed={showClosed} />
    </>
  );
}
