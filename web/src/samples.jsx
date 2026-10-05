import { useState } from "react";
import {
  collection,
  collectionGroup,
  getDocs,
  limit,
  onSnapshot,
  orderBy,
  query,
} from "firebase/firestore";
import { db } from "./firebase.js";
import { ErrCard, useDoc, useListen, useLog, when } from "./ui.jsx";
import { TraceCard } from "./trace.jsx";
import { firstWithAudio, lastBrief, lastRouted } from "./pick.js";

// Read-only panels so a judge sees the AI output without any POST. Firestore reads only.

const FALLBACK = {
  stage: "SAMPLE",
  text: "Sample alert (bundled demo audio)",
  audio_url: "/sample-alert.mp3",
};

// Plays the newest alert that has speech; falls back to the bundled MP3 when there is none or the read fails.
// play(alert, onBlocked) is the page's own speak(), so one sound at a time.
export function SampleAlert({ play }) {
  const [a, setA] = useState(null);
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  async function go() {
    setBusy(true);
    setBlocked(false);
    let row = null;
    try {
      const q = await getDocs(
        query(collectionGroup(db, "alerts"), orderBy("created_at", "desc"), limit(10)),
      );
      row = firstWithAudio(q.docs.map((d) => d.data()));
    } catch (e) {
      console.warn("sample alert read failed, using the bundled clip:", e.message);
    }
    const alert = row ?? FALLBACK;
    setA(alert);
    play(alert, () => setBlocked(true));
    setBusy(false);
  }
  return (
    <section className="card">
      <button onClick={go} disabled={busy}>
        {busy ? "Loading…" : "▶ Sample alert"}
      </button>
      <div role="status">
        {a && (
          <>
            <p className="alert-text">{a.text_local || a.text}</p>
            {a.text_local && <p className="alert-en">{a.text}</p>}
          </>
        )}
        {blocked && <p className="muted">Sound is blocked by the browser. Tap again.</p>}
      </div>
      <p className="muted">Plays the latest recorded alert. Nothing is sent.</p>
    </section>
  );
}

// Live read of the newest `n` docs of a collection (order field desc) -> {data, loading, error, retry}.
const useNewest = (name, field, n) =>
  useListen(
    (ok, bad) =>
      onSnapshot(
        query(collection(db, name), orderBy(field, "desc"), limit(n)),
        (q) => ok(q.docs.map((d) => ({ id: d.id, ...d.data() }))),
        bad,
      ),
    [name],
  );

const ATMIST = [
  ["age", "Age"],
  ["time", "Time"],
  ["mechanism", "Mechanism"],
  ["injuries", "Injuries"],
  ["signs", "Signs"],
  ["treatment", "Treatment"],
];

// "Last handover": newest briefs/* written by a model (not the offline stub), with that run's logged interventions.
export function LastHandover({ Chips }) {
  const s = useNewest("briefs", "generated_at", 10);
  const b = s.data ? lastBrief(s.data) : null;
  const log = useLog(b?.id);
  const seen = new Set();
  const items = (log.rows ?? [])
    .flatMap((e) => e.interventions ?? [])
    .filter((i) => {
      const k = [i.name, i.dose].join("|").toLowerCase();
      return !seen.has(k) && seen.add(k);
    });
  return (
    <section className="card">
      <h2 style={{ marginTop: 0 }}>Last handover</h2>
      <ErrCard what="the last handover" error={s.error} retry={s.retry} />
      {s.loading ? (
        <p className="muted">Loading…</p>
      ) : s.error ? null : !b ? (
        <p className="muted">No handover yet</p>
      ) : (
        <>
          <p className="muted">
            Run {b.id} · generated {when(b.generated_at)}
          </p>
          <dl className="atmist">
            {ATMIST.map(([k, l]) => (
              <div key={k} style={{ display: "contents" }}>
                <dt>{l}</dt>
                <dd>{b.atmist?.[k] ?? "—"}</dd>
              </div>
            ))}
          </dl>
          {b.summary && <p className="summary">{b.summary}</p>}
          <Chips items={items} />
          <ul>
            {(b.checklist ?? []).map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
          <p className="banner">{b.disclaimer ?? "A clinician confirms these values."}</p>
        </>
      )}
    </section>
  );
}

// "Last routing decision": newest run whose hospital routing was applied (or shows a multi-step trace).
export function LastRouting() {
  const s = useNewest("runs", "started_at", 25);
  const r = s.data ? lastRouted(s.data) : null;
  return (
    <section>
      <h2>Last routing decision</h2>
      <ErrCard what="the last routing decision" error={s.error} retry={s.retry} />
      {s.loading ? (
        <p className="muted">Loading…</p>
      ) : s.error ? null : !r ? (
        <p className="muted">No routing decision yet</p>
      ) : (
        <>
          <p className="muted">
            {r.vehicle_plate ?? r.id} · run {r.id}
          </p>
          <TraceCard routing={r.routing} />
        </>
      )}
    </section>
  );
}

// Report-card heading: the vehicle plate and tier of a run instead of its raw id (run id while the run doc loads).
export function RunLabel({ id, tier }) {
  const r = useDoc(`runs/${id}`).data;
  const t = tier ?? r?.confirmed_tier ?? r?.acuity_tier;
  return (
    <b>
      {r?.vehicle_plate ?? id}
      {t ? ` · ${t}` : ""}
    </b>
  );
}
