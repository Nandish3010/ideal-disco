import { useEffect, useState } from "react";
import { collection, onSnapshot } from "firebase/firestore";
import { db } from "../firebase.js";
import { api } from "../api.js";
import { corridors } from "../data.js";
import { ErrCard, useDoc, when } from "../ui.jsx";
import { ms, useEnRoute, useNow } from "./Cop.jsx";
import { Chips, Thumb } from "./Vehicle.jsx";
import { LastHandover } from "../samples.jsx";
import "../cop.css";

const eta = (r, now) =>
  r.eta_hospital_s == null
    ? null
    : Math.max(0, r.eta_hospital_s - (now - (ms(r.last_tick_at) ?? now)) / 1000);
const mmss = (s) =>
  s == null ? "—" : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const tierOf = (r) => r.confirmed_tier ?? r.acuity_tier ?? "unknown";
const flat = (o, p = "") =>
  Object.entries(o ?? {}).flatMap(([k, v]) =>
    v == null || k === "transcript_en"
      ? []
      : typeof v === "object"
        ? flat(v, k + ".")
        : [[p + k, String(v)]],
  );

function useLog(id) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    setRows([]);
    return onSnapshot(
      collection(db, "runs", id, "log"),
      (q) =>
        setRows(
          q.docs.map((d) => ({ n: d.id, ...d.data() })).sort((a, b) => Number(a.n) - Number(b.n)),
        ),
      () => {},
    );
  }, [id]);
  return rows;
}

// "Aspirin 300 mg · Oxygen 4 L": every intervention across the log, once each, in the order given.
function Treatment({ log }) {
  const seen = new Set();
  const items = log
    .flatMap((e) => e.interventions ?? [])
    .map((i) => [i.name, i.dose].filter(Boolean).join(" "))
    .filter((t) => t && !seen.has(t.toLowerCase()) && seen.add(t.toLowerCase()))
    .map((t) => t[0].toUpperCase() + t.slice(1));
  return items.length ? (
    <p>
      <b>Treatment so far:</b> {items.join(" · ")}
    </p>
  ) : null;
}

function Vitals({ log }) {
  // newest entry that has the value wins, photo entries included
  const series = (k) => log.map((e) => e.fields?.vitals?.[k]).filter((v) => v != null);
  return (
    <div className="vitals">
      {[
        ["sbp", "SBP"],
        ["hr", "HR"],
        ["spo2", "SpO2"],
      ].map(([k, label]) => {
        const s = series(k);
        return (
          <div key={k}>
            <span className="muted">{label}</span>
            <b>{s.length ? s.at(-1) : "—"}</b>
            <span className="muted">
              {s.length > 1 ? `${label} ${s.slice(-3).join(" → ")}` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Brief({ runId }) {
  const { data } = useDoc(`briefs/${runId}`);
  const [fresh, setFresh] = useState(null); // response of a manual regenerate, in case the doc lags
  const [ticks, setTicks] = useState({});
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setFresh(null);
    setTicks({});
    setNote("");
  }, [runId]);
  async function regen() {
    setBusy(true);
    setNote("");
    try {
      setFresh(await api("/brief", { run_id: runId }));
    } catch (e) {
      setNote(`Could not generate: ${e.message}`);
    }
    setBusy(false);
  }
  const b = fresh ?? data;
  return (
    <section className="card">
      <h2 style={{ marginTop: 0 }}>Brief</h2>
      {!b ? (
        <p className="muted">Brief arrives when the ambulance is 5 minutes out</p>
      ) : (
        <>
          <dl className="atmist">
            {[
              ["age", "Age"],
              ["time", "Time"],
              ["mechanism", "Mechanism"],
              ["injuries", "Injuries"],
              ["signs", "Signs"],
              ["treatment", "Treatment"],
            ].map(([k, l]) => (
              <div key={k} style={{ display: "contents" }}>
                <dt>{l}</dt>
                <dd>{b.atmist?.[k] ?? "—"}</dd>
              </div>
            ))}
          </dl>
          {b.summary && <p className="summary">{b.summary}</p>}
          {(b.checklist ?? []).map((c, i) => (
            <label className="check" key={i}>
              <input
                type="checkbox"
                checked={!!ticks[i]}
                onChange={(e) => setTicks({ ...ticks, [i]: e.target.checked })}
              />
              {c}
            </label>
          ))}
          <p className="banner">{b.disclaimer ?? "A clinician confirms these values."}</p>
          <p className="muted">Generated {when(b.generated_at)}.</p>
        </>
      )}
      <button onClick={regen} disabled={busy}>
        {busy ? "Working…" : "Regenerate brief"}
      </button>
      {note && <p className="muted">{note}</p>}
    </section>
  );
}

// Button + report for a finished run; the server stores the first one and returns it again.
export function AfterAction({ runId }) {
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    setError("");
    try {
      setDoc(await api(`/runs/${runId}/after-action`));
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  }
  return (
    <section className="card">
      <h2 style={{ marginTop: 0 }}>After-action report</h2>
      <button onClick={go} disabled={busy}>
        {busy ? "Working…" : "Generate after-action report"}
      </button>
      <ErrCard what="the after-action report" error={error} retry={go} />
      {doc && (
        <>
          <p className="summary">{doc.summary}</p>
          <ol className="timeline">
            {(doc.timeline ?? []).map((e, i) => (
              <li key={i}>
                <span className="muted">{when(e.t)}</span> {e.event}
              </li>
            ))}
          </ol>
          <h3>Issues</h3>
          <ul>
            {(doc.issues ?? []).map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
          <h3>Recommendations</h3>
          <ul>
            {(doc.recommendations ?? []).map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
          <p className="banner">{doc.disclaimer}</p>
        </>
      )}
    </section>
  );
}

function Selected({ run }) {
  const log = useLog(run.id);
  return (
    <>
      <h2>Vitals</h2>
      <Vitals log={log} />
      <Treatment log={log} />
      <h2>Transit log</h2>
      {log.length === 0 && <p className="muted">No log entries yet.</p>}
      <ol className="timeline">
        {log.map((e) => (
          <li key={e.n}>
            <span className="muted">{when(e.t)}</span> <span className="pill">{e.kind}</span>
            {e.confirmed ? (
              <b className="tier-stable"> ✓ crew confirmed</b>
            ) : (
              <span className="muted"> unconfirmed</span>
            )}
            <Thumb url={e.photo_url} />
            <div>{e.transcript_en}</div>
            <Chips items={e.interventions} />
            <dl className="kv">
              {flat(e.fields).map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ol>
      <Brief runId={run.id} />
      {["ended", "arrived"].includes(run.state) && <AfterAction runId={run.id} />}
    </>
  );
}

export default function Hospital() {
  const q = new URLSearchParams(location.search).get("corridor");
  const hospital = (corridors[q] ?? corridors.blr).hospital.name;
  const { runs, error } = useEnRoute();
  const now = useNow();
  const [pick, setPick] = useState(null);
  // ponytail: /runs destination is optional; an ambulance run with none is taken to be bound for its corridor's hospital
  const inbound = runs
    .filter((r) =>
      r.destination
        ? r.destination.name === hospital
        : r.vehicle_type === "ambulance" && (r.corridor ?? "blr") === (corridors[q] ? q : "blr"),
    )
    .sort((a, b) => (eta(a, now) ?? 1e9) - (eta(b, now) ?? 1e9));
  const sel = inbound.find((r) => r.id === pick) ?? inbound[0];
  return (
    <>
      <p className="banner">Demo: synthetic patients only</p>
      <h2 style={{ marginTop: 0 }}>{hospital}</h2>
      {error && <p className="card bad">Could not load runs: {error}</p>}
      {inbound.length === 0 && <p className="muted">No inbound ambulances.</p>}
      <div className="runs">
        {inbound.map((r) => (
          <button key={r.id} aria-pressed={r.id === sel?.id} onClick={() => setPick(r.id)}>
            <span className="countdown">{mmss(eta(r, now))}</span>
            <span className={`pill tier-${tierOf(r)}`}>{tierOf(r)}</span> {r.vehicle_type}
            <div className="muted">
              {r.incident_id} · {r.id}
            </div>
          </button>
        ))}
      </div>
      {sel && <Selected key={sel.id} run={sel} />}
      <LastHandover Chips={Chips} />
    </>
  );
}
