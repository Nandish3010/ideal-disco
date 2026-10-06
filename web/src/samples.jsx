import { useEffect, useRef, useState } from "react";
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
import { vehicleLabel } from "./format.js";
import { ErrCard, useDoc, useListen, useLog, when } from "./ui.jsx";
import { TraceCard } from "./trace.jsx";
import { firstWithAudio, lastBrief, lastRouted } from "./pick.js";
import { t } from "./i18n/index.js";

// Read-only panels so a judge sees the AI output without any POST. Firestore reads only.

// ?sample=1 / ?last=1 (the landing page shortcuts) bring that panel into view.
function useScrollTo(param) {
  const el = useRef(null);
  useEffect(() => {
    if (new URLSearchParams(location.search).get(param) === "1")
      el.current?.scrollIntoView({ block: "center" });
  }, [param]);
  return el;
}

const FALLBACK = {
  stage: "SAMPLE",
  text: "Sample alert (bundled demo audio)",
  audio_url: "/sample-alert.mp3",
};

// Plays the newest alert that has speech; falls back to the bundled MP3 when there is none or the read fails.
// play(alert, onBlocked) is the page's own speak(), so one sound at a time.
export function SampleAlert({ play }) {
  const el = useScrollTo("sample");
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
    <section className="card" ref={el}>
      <button onClick={go} disabled={busy}>
        {busy ? t("common.loading") : `▶ ${t("sample.play")}`}
      </button>
      <div role="status">
        {a && (
          <>
            <p className="alert-text">{a.text_local || a.text}</p>
            {a.text_local && <p className="alert-en">{a.text}</p>}
          </>
        )}
        {blocked && <p className="muted">{t("sample.blocked")}</p>}
      </div>
      <p className="muted">{t("sample.note")}</p>
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

const ATMIST = ["age", "time", "mechanism", "injuries", "signs", "treatment"];

// "Last handover": newest briefs/* written by a model (not the offline stub), with that run's logged interventions.
export function LastHandover({ Chips }) {
  const el = useScrollTo("last");
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
    <section className="card" ref={el}>
      <h2 style={{ marginTop: 0 }}>{t("sample.handover")}</h2>
      <ErrCard what={t("what.handover")} error={s.error} retry={s.retry} />
      {s.loading ? (
        <p className="muted">{t("common.loading")}</p>
      ) : s.error ? null : !b ? (
        <p className="muted">{t("sample.no_handover")}</p>
      ) : (
        <>
          <p className="muted">{t("sample.run_gen", { id: b.id, at: when(b.generated_at) })}</p>
          <dl className="atmist">
            {ATMIST.map((k) => (
              <div key={k} style={{ display: "contents" }}>
                <dt>{t(`hospital.a_${k}`)}</dt>
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
          <p className="banner">{b.disclaimer ?? t("hospital.disclaimer")}</p>
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
      <h2>{t("sample.routing")}</h2>
      <ErrCard what={t("what.routing")} error={s.error} retry={s.retry} />
      {s.loading ? (
        <p className="muted">{t("common.loading")}</p>
      ) : s.error ? null : !r ? (
        <p className="muted">{t("sample.no_routing")}</p>
      ) : (
        <>
          <p className="muted">
            {t("sample.plate_run", { plate: r.vehicle_plate ?? r.id, id: r.id })}
          </p>
          <TraceCard routing={r.routing} />
        </>
      )}
    </section>
  );
}

// Report-card heading: the vehicle plate and tier of a run instead of its raw id (run id while the run doc loads).
export function RunLabel({ id, tier, type }) {
  const r = useDoc(`runs/${id}`).data;
  const t = tier ?? r?.confirmed_tier ?? r?.acuity_tier;
  const ty = type ?? r?.vehicle_type;
  return (
    <b>
      {r?.vehicle_plate ?? id}
      {ty || t ? ` · ${vehicleLabel(ty, t)}` : ""}
    </b>
  );
}
