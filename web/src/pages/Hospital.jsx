import { useEffect, useState } from "react";
import { collection, onSnapshot } from "firebase/firestore";
import { db } from "../firebase.js";
import { api } from "../api.js";
import { corridors } from "../data.js";
import { HOSPITALS } from "../hospitals.js";
import { ErrCard, Field, store, useDoc, when } from "../ui.jsx";
import { ms, useEnRoute, useNow } from "./Cop.jsx";
import { Chips, Thumb } from "./Vehicle.jsx";
import { LastHandover } from "../samples.jsx";
import Coach from "../a11y/Coach.jsx";
import { t } from "../i18n/index.js";
import "../cop.css";

// The hospital desk token (POST /hospital/duty) lets this page regenerate briefs and reports; the roster id is the server's.
const HOSPITAL_ID = { blr: "blr_jayadeva", hyd: "hyd_continental" };
const deskId = () => {
  const p = new URLSearchParams(location.search);
  const picked = Object.values(HOSPITALS)
    .flat()
    .find((h) => h.id === p.get("hospital"));
  return picked?.id ?? HOSPITAL_ID[p.get("corridor")] ?? HOSPITAL_ID.blr; // ?hospital= wins, else the corridor's own
};
const deskToken = () => store.get(`hospital_token_${deskId()}`) || undefined; // undefined: api() falls back to the vehicle token

// Up/Down/Home/End move focus along the run list (every run is also a normal tab stop).
function arrows(e) {
  const keys = { ArrowDown: 1, ArrowUp: -1, Home: "first", End: "last" };
  if (!(e.key in keys)) return;
  const all = [...e.currentTarget.querySelectorAll("button")];
  const i = all.indexOf(document.activeElement);
  const k = keys[e.key];
  const next = k === "first" ? all[0] : k === "last" ? all.at(-1) : all[i + k];
  if (next) {
    e.preventDefault();
    next.focus();
  }
}

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
      <b>{t("hospital.treatment_so_far")}</b> {items.join(" · ")}
    </p>
  ) : null;
}

function Vitals({ log }) {
  // newest entry that has the value wins, photo entries included
  const series = (k) => log.map((e) => e.fields?.vitals?.[k]).filter((v) => v != null);
  return (
    <div className="vitals">
      {[
        ["sbp", "SBP"], // clinical abbreviations stay in Latin script
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
      setFresh(await api("/brief", { run_id: runId, regenerate: true }, deskToken()));
    } catch (e) {
      setNote(t("hospital.gen_failed", { msg: e.message }));
    }
    setBusy(false);
  }
  const b = fresh ?? data;
  return (
    <section className="card">
      <h2 style={{ marginTop: 0 }}>{t("hospital.brief")}</h2>
      {!b ? (
        <p className="muted">{t("hospital.brief_wait")}</p>
      ) : (
        <>
          <dl className="atmist">
            {["age", "time", "mechanism", "injuries", "signs", "treatment"].map((k) => (
              <div key={k} style={{ display: "contents" }}>
                <dt>{t(`hospital.a_${k}`)}</dt>
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
          <p className="banner">{b.disclaimer ?? t("hospital.disclaimer")}</p>
          <p className="muted">{t("hospital.generated", { at: when(b.generated_at) })}</p>
        </>
      )}
      <button onClick={regen} disabled={busy}>
        {busy ? t("common.working") : t("hospital.regen")}
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
      setDoc(await api(`/runs/${runId}/after-action`, {}, deskToken()));
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  }
  return (
    <section className="card">
      <h2 style={{ marginTop: 0 }}>{t("hospital.aar")}</h2>
      <button onClick={go} disabled={busy}>
        {busy ? t("common.working") : t("hospital.aar_gen")}
      </button>
      <ErrCard what={t("what.aar")} error={error} retry={go} />
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
          <h3>{t("hospital.issues")}</h3>
          <ul>
            {(doc.issues ?? []).map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
          <h3>{t("hospital.recs")}</h3>
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
      <h2>{t("hospital.vitals")}</h2>
      <Vitals log={log} />
      <Treatment log={log} />
      <h2>{t("hospital.log")}</h2>
      {log.length === 0 && <p className="muted">{t("hospital.log_none")}</p>}
      <ol className="timeline">
        {log.map((e) => (
          <li key={e.n}>
            <span className="muted">{when(e.t)}</span> <span className="pill">{e.kind}</span>
            {e.confirmed ? (
              <b className="tier-stable"> ✓ {t("hospital.confirmed")}</b>
            ) : (
              <span className="muted"> {t("hospital.unconfirmed")}</span>
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
  const params = new URLSearchParams(location.search);
  const q = params.get("corridor");
  // ?hospital=<roster id> picks the hospital (and so its corridor); without it, the corridor's own hospital
  const fromId = Object.entries(HOSPITALS).find(([, hs]) =>
    hs.some((h) => h.id === params.get("hospital")),
  );
  const cid = fromId?.[0] ?? (corridors[q] ? q : "blr");
  const roster = HOSPITALS[cid];
  const [hid, setHid] = useState(
    (fromId && params.get("hospital")) ??
      roster.find((h) => h.name === corridors[cid].hospital.name)?.id ??
      roster[0].id,
  );
  const hospital = roster.find((h) => h.id === hid).name;
  const choose = (id) => {
    history.replaceState(null, "", `?corridor=${cid}&hospital=${id}`);
    setHid(id);
    setDesk(!!deskToken()); // the desk token is per hospital
  };
  const { runs, error } = useEnRoute();
  const now = useNow();
  const [pick, setPick] = useState(null);
  const [desk, setDesk] = useState(!!deskToken());
  async function signIn() {
    try {
      store.set(
        `hospital_token_${deskId()}`,
        (await api("/hospital/duty", { hospital_id: deskId() })).hospital_token,
      );
      setDesk(true);
    } catch {
      setDesk(false);
    }
  }
  // ponytail: /runs destination is optional; an ambulance run with none is taken to be bound for its corridor's hospital
  const inbound = runs
    .filter((r) =>
      r.destination
        ? r.destination.name === hospital
        : r.vehicle_type === "ambulance" &&
          (r.corridor ?? "blr") === cid &&
          hospital === corridors[cid].hospital.name,
    )
    .sort((a, b) => (eta(a, now) ?? 1e9) - (eta(b, now) ?? 1e9));
  const sel = inbound.find((r) => r.id === pick) ?? inbound[0];
  return (
    <>
      <p className="banner">{t("hospital.demo")}</p>
      <Coach role="hospital" />
      <Field label={t("hospital.hospital")}>
        <select value={hid} onChange={(e) => choose(e.target.value)}>
          {roster.map((h) => (
            <option key={h.id} value={h.id}>
              {h.name}
            </option>
          ))}
        </select>
      </Field>
      <h2>{hospital}</h2>
      <button onClick={signIn} disabled={desk}>
        {desk ? t("hospital.desk_in") : t("hospital.desk_sign")}
      </button>
      {error && (
        <p className="card bad" role="alert">
          {t("common.load_failed", { what: t("what.runs"), error })}
        </p>
      )}
      {inbound.length === 0 && <p className="muted">{t("hospital.none")}</p>}
      <div className="runlist" role="group" aria-label={t("hospital.inbound")} onKeyDown={arrows}>
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
