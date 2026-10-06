import { useEffect, useRef, useState } from "react";
import {
  collection,
  collectionGroup,
  doc,
  getDoc,
  getDocs,
  limit,
  onSnapshot,
  orderBy,
  query,
} from "firebase/firestore";
import { db } from "./firebase.js";
import { shortId, vehicleLabel } from "./format.js";
import { ErrCard, useDoc, useListen, useLog, when } from "./ui.jsx";
import { TraceCard } from "./trace.jsx";
import { handover, routedRun, sampleAlert } from "./pick.js";
import { t } from "./i18n/index.js";

// Read-only panels so a judge sees the AI output without any POST. Firestore reads only.
// settings/showcase (written by scripts/pin_showcase.py) pins one good run for them: {run_id, alert_path, brief_run_id, note}.
// Each panel prefers the pin and falls back to the newest suitable data when it is missing or stale.
const usePin = () => useDoc("settings/showcase").data;

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

// Plays the pinned alert, else the PREPARE alert with speech and the longest queue; falls back to the bundled MP3 when
// there is none or the read fails.
// play(alert, onBlocked) is the page's own speak(), so one sound at a time.
export function SampleAlert({ play }) {
  const el = useScrollTo("sample");
  const pin = usePin();
  const [a, setA] = useState(null);
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  async function go() {
    setBusy(true);
    setBlocked(false);
    let row = null;
    try {
      if (pin?.alert_path) {
        const d = await getDoc(doc(db, pin.alert_path));
        if (d.exists() && d.data().audio_url) row = d.data();
      }
      if (!row) {
        const q = await getDocs(
          query(collectionGroup(db, "alerts"), orderBy("created_at", "desc"), limit(50)),
        );
        row = sampleAlert(q.docs.map((d) => d.data()));
      }
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

// "Last handover": the pinned brief when its run went to `hospital` (a roster name), else the newest model-written brief
// (not the offline stub) of a run bound there, with that run's logged interventions.
export function LastHandover({ Chips, hospital }) {
  const el = useScrollTo("last");
  const pin = usePin();
  const pinned = useDoc(pin?.brief_run_id ? `briefs/${pin.brief_run_id}` : null).data;
  const pinnedRun = useDoc(pin?.brief_run_id ? `runs/${pin.brief_run_id}` : null).data;
  const bs = useNewest("briefs", "generated_at", 25);
  const rs = useNewest("runs", "started_at", 25);
  const s = {
    loading: bs.loading || rs.loading,
    error: bs.error || rs.error,
    retry: () => (bs.retry(), rs.retry()),
  };
  const b =
    bs.data && rs.data
      ? handover({
          pinned: pinned && { id: pin.brief_run_id, ...pinned },
          pinnedRun,
          briefs: bs.data,
          runs: rs.data,
          hospital,
        })
      : null;
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
          <p className="muted" title={b.id}>
            {t("sample.run_gen", { id: shortId(b.id), at: when(b.generated_at) })}
          </p>
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

// "Last routing decision": the pinned run, else the newest run whose hospital routing was applied (or shows a multi-step trace).
export function LastRouting() {
  const pin = usePin();
  const pinnedRun = useDoc(pin?.run_id ? `runs/${pin.run_id}` : null).data;
  const s = useNewest("runs", "started_at", 25);
  const r = s.data ? routedRun(pinnedRun && { id: pin.run_id, ...pinnedRun }, s.data) : null;
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
          <p className="muted" title={r.id}>
            {t("sample.plate_run", { plate: r.vehicle_plate ?? shortId(r.id), id: shortId(r.id) })}
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
    <b title={id}>
      {r?.vehicle_plate ?? shortId(id)}
      {ty || t ? ` · ${vehicleLabel(ty, t)}` : ""}
    </b>
  );
}
