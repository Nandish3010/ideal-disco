import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { corridors } from "../data.js";
import { TraceCard } from "../trace.jsx";
import {
  Err,
  Field,
  MAX_S,
  b64,
  deviceId,
  holdProps,
  store,
  useDoc,
  useHold,
  useLog,
  when,
} from "../ui.jsx";
import { LastRouting } from "../samples.jsx";
import { collection, getDocs, limit, onSnapshot, orderBy, query } from "firebase/firestore";
import { copNoteText, currentAlert, tierLabel } from "../format.js";
import { db } from "../firebase.js";
import { latestOpen } from "../pick.js";
import Coach from "../a11y/Coach.jsx";
import { t } from "../i18n/index.js";

// Demo vehicles seeded in the registry (see the sim scenarios).
const DEMO_PLATES = [
  ["KA01AB1234", "ambulance, critical"],
  ["KA01AB4321", "ambulance, critical stroke"],
  ["KA01FE5678", "fire engine"],
];
// Indian plate: state code, 1-2 digit district, 1-3 letter series, up to 4 digits (KA01AB1234); incident: INC- + 6 hex.
const PLATE_RE = /^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{1,4}$/;
const INCIDENT_RE = /^INC-[0-9A-F]{6}$/;

function Bind({ bound, setBound }) {
  const [plate, setPlate] = useState(store.get("plate") ?? DEMO_PLATES[0][0]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [bad, setBad] = useState(null); // inline problem with the plate field
  const input = useRef(null);

  async function submit(e) {
    e.preventDefault();
    const p = plate.replace(/[\s-]/g, "").toUpperCase(); // KA 01-AB 1234 -> KA01AB1234
    if (!PLATE_RE.test(p)) {
      setBad(t("vehicle.plate_bad"));
      return input.current?.focus();
    }
    setBad(null);
    setBusy(true);
    setErr(null);
    setBound(null);
    store.set("plate", p);
    try {
      // the token goes in its own key (api.js sends it as X-Device-Token), not into the bound record
      const { device_token, ...r } = await api("/vehicles/bind", {
        plate: p,
        device_id: deviceId(),
      });
      store.set("vehicle_token", device_token);
      store.set("bound", JSON.stringify(r));
      setBound(r);
    } catch (x) {
      store.set("bound", null);
      store.set("vehicle_token", null);
      setErr(x);
    }
    setBusy(false);
  }

  return (
    <section>
      <h2>{t("vehicle.bind_h")}</h2>
      <form className="card" onSubmit={submit} noValidate>
        <Field
          label={t("vehicle.plate")}
          error={bad ?? (err?.status === 404 ? t("vehicle.unregistered_short") : null)}
        >
          <input
            ref={input}
            value={plate}
            onChange={(e) => setPlate(e.target.value)}
            placeholder="KA01AB1234"
            autoCapitalize="characters"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            enterKeyHint="go"
            autoFocus={!bound}
            required
          />
        </Field>
        <div className="chips" role="group" aria-label={t("vehicle.demo_plates")}>
          {DEMO_PLATES.map(([p, what]) => (
            <button
              type="button"
              key={p}
              className="chip"
              aria-label={t("vehicle.use_plate", { plate: p, what })}
              onClick={() => setPlate(p)}
            >
              {p}
            </button>
          ))}
        </div>
        <button className="primary" disabled={busy}>
          {busy ? t("vehicle.binding") : t("vehicle.bind")}
        </button>
      </form>
      {err?.status === 404 ? (
        <div className="card reject" role="alert">
          <div className="big">{t("vehicle.unregistered")}</div>
          <p>{t("vehicle.unregistered_p", { plate: plate.trim().toUpperCase() })}</p>
        </div>
      ) : (
        <Err e={err} />
      )}
      {bound && (
        <div className="card good" role="status">
          <div className="big">{t("vehicle.bound", { plate: bound.plate })}</div>
          <p>
            {t("vehicle.type")}: <b>{bound.type}</b> · {t("vehicle.agency")}: <b>{bound.agency}</b>
          </p>
        </div>
      )}
    </section>
  );
}

// Posts position to /location at most every 5 s while a run is active.
function useGps(runId, active) {
  const [note, setNote] = useState("");
  const last = useRef(0);
  useEffect(() => {
    if (!active || !runId) return;
    if (!navigator.geolocation) {
      setNote(t("vehicle.gps_none"));
      return;
    }
    setNote(t("vehicle.gps_wait"));
    const id = navigator.geolocation.watchPosition(
      async (p) => {
        if (Date.now() - last.current < 5000) return;
        last.current = Date.now();
        const c = p.coords;
        try {
          await api("/location", {
            run_id: runId,
            lat: c.latitude,
            lng: c.longitude,
            speed_mps: c.speed ?? 0,
            heading: c.heading,
            t: new Date(p.timestamp).toISOString(),
            source: "gps",
          });
          setNote(t("vehicle.gps_sent", { at: new Date().toLocaleTimeString() }));
        } catch (e) {
          console.log("/location failed", e);
          setNote(t("vehicle.gps_fail", { msg: e.message }));
        }
      },
      (e) => setNote(t("vehicle.gps_err", { msg: e.message })),
      { enableHighAccuracy: true },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [runId, active]);
  return note;
}

const flat = (o, p = "") =>
  Object.entries(o ?? {}).flatMap(([k, v]) =>
    k === "transcript_en" || v == null
      ? []
      : typeof v === "object"
        ? flat(v, k + ".")
        : [[p + k, v]],
  );
const show = (v) => (v === true ? "yes" : v === false ? "no" : String(v));
const clock = (s) => `0:${String(Math.floor(s)).padStart(2, "0")}`;
const heard = (t, v) =>
  new RegExp("\\b" + show(v).replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "i").test(t ?? "");

// Downscale a photo to <= 1280 px, JPEG q0.8; shrink again while the base64 is over 2 MB. -> {b64, url}
const MAX_PX = 1280,
  MAX_B64 = 2 * 1024 * 1024;
async function shrink(file) {
  const img = await createImageBitmap(file, { imageOrientation: "from-image" });
  let scale = Math.min(1, MAX_PX / Math.max(img.width, img.height)),
    url;
  const cv = document.createElement("canvas");
  for (let i = 0; i < 6; i++) {
    cv.width = Math.round(img.width * scale);
    cv.height = Math.round(img.height * scale);
    cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
    url = cv.toDataURL("image/jpeg", 0.8 - i * 0.05);
    if (url.length - 23 <= MAX_B64) break;
    scale *= 0.75;
  }
  img.close?.();
  return { b64: url.split(",")[1], url };
}

const ICON = { drug: "💊", procedure: "🩺", observation: "👁" };
const label = (i) => [i.name, i.dose].filter(Boolean).join(" ");
// Intervention chips + tap-to-open photo thumbnail, shared with the hospital page.
export const Chips = ({ items }) =>
  items?.length ? (
    <div className="chips">
      {items.map((i, k) => (
        <span
          key={k}
          className={"chip " + (i.kind ?? "")}
          title={[i.route, i.time_note].filter(Boolean).join(" · ") || undefined}
        >
          {ICON[i.kind] ?? "•"} {label(i)}
        </span>
      ))}
    </div>
  ) : null;
export const Thumb = ({ url }) =>
  typeof url === "string" && url.startsWith("https://") ? (
    <a href={url} target="_blank" rel="noopener noreferrer">
      <img className="thumb" src={url} alt={t("vehicle.monitor_photo")} loading="lazy" />
    </a>
  ) : null;

function Fields({ fields, transcript, photo }) {
  const rows = flat(fields);
  if (!rows.length) return <p className="muted">{t("vehicle.no_fields")}</p>;
  return (
    <dl className="kv">
      {rows.map(([k, v]) => {
        const ok = photo || heard(transcript, v);
        return (
          <div key={k}>
            <dt>{k}</dt>
            <dd>
              {show(v)}
              <small className={ok ? "src" : "inf"}>
                {photo
                  ? t("vehicle.from_photo")
                  : ok
                    ? t("vehicle.in_transcript")
                    : t("vehicle.inferred")}
              </small>
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

function Triage({ runId, vehicleType, confirmed, setDone }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [res, setRes] = useState(null); // {...response, log}
  const [pick, setPick] = useState(null); // manual mode override
  const [confirming, setConfirming] = useState(false);
  const [cerr, setCerr] = useState(null);
  const [note, setNote] = useState("");
  const [shot, setShot] = useState(null); // data URL of the monitor photo behind the current send, else null
  const area = useRef(null);
  const mode = pick ?? (confirmed ? "log" : "triage");

  async function send(extra, kind, url = null) {
    const log = mode === "log";
    setBusy(true);
    setErr(null);
    setRes(null);
    setNote("");
    setShot(url);
    try {
      setRes({
        ...(await api(log ? "/log" : "/triage", {
          run_id: runId,
          vehicle_type: vehicleType,
          ...(log && { kind }),
          ...extra,
        })),
        log,
      });
      if (kind === "form") setText("");
    } catch (x) {
      setErr(x);
    }
    setBusy(false);
  }
  async function confirm() {
    setConfirming(true);
    setCerr(null);
    try {
      setDone((await api(`/runs/${runId}/confirm`, { tier: res.suggested_tier })).confirmed_tier);
      setPick(null);
    } catch (x) {
      setCerr(x);
    }
    setConfirming(false);
  }
  async function photo(e) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setBusy(true);
    setErr(null);
    setRes(null);
    setNote("");
    setShot("pending");
    let r;
    try {
      r = await shrink(f);
    } catch {
      setBusy(false);
      setShot(null);
      return setNote(t("vehicle.photo_fail"));
    }
    send({ image_b64: r.b64, mime: "image/jpeg" }, "photo", r.url);
  }
  const hold = useHold(async (blob) => {
    if (!blob) return setNote(t("vehicle.too_short"));
    setBusy(true);
    send({ audio_b64: await b64(blob), mime: blob.type.split(";")[0] || "audio/webm" }, "voice");
  });
  const failed = err?.body?.error === "extraction_failed";
  // 400/422 = the image could not be read
  const unread = shot && [400, 422].includes(err?.status);
  useEffect(() => {
    if (failed || unread || hold.mic) area.current?.focus();
  }, [failed, unread, hold.mic]);

  const tier = res?.suggested_tier;
  const up = tierLabel(tier).toUpperCase();
  return (
    <section>
      <h2>{t("vehicle.patient_h")}</h2>
      <div className="row" role="group" aria-label={t("vehicle.note_type")}>
        {[
          ["triage", t("vehicle.triage")],
          ["log", t("vehicle.log_note")],
        ].map(([m, l]) => (
          <button
            key={m}
            type="button"
            className={mode === m ? "on" : ""}
            aria-pressed={mode === m}
            onClick={() => setPick(m)}
          >
            {l}
          </button>
        ))}
      </div>
      <button
        className={"giant" + (hold.on ? " live" : "")}
        disabled={busy}
        aria-describedby="speak-hint"
        {...holdProps(hold)}
      >
        {busy
          ? shot
            ? t("vehicle.reading")
            : t("vehicle.thinking")
          : hold.on
            ? t("vehicle.listening", { clock: clock(hold.s) })
            : t("vehicle.hold")}
        {hold.on && (
          <small>
            {t("vehicle.s_left", { n: Math.max(0, Math.ceil(MAX_S - hold.s)) })}
            <span className="meter">
              <i style={{ width: Math.min(100, (hold.s / MAX_S) * 100) + "%" }} />
            </span>
          </small>
        )}
      </button>
      <p id="speak-hint" className="sr-only">
        {t("vehicle.hold_hint")}
      </p>
      <label className={"btn photo" + (busy ? " off" : "")}>
        {busy && shot ? t("vehicle.reading") : `📷 ${t("vehicle.photo")}`}
        <input
          type="file"
          accept="image/*"
          capture="environment"
          disabled={busy}
          onChange={photo}
          className="sr-only"
        />
      </label>
      {note && (
        <p className="muted" role="status">
          {note}
        </p>
      )}
      {hold.mic && (
        <p className="card bad" role="alert">
          {hold.mic === "denied" ? t("cop.mic_denied") : t("cop.mic_unavailable")}{" "}
          {t("cop.type_instead")}
        </p>
      )}
      <form
        className="card"
        onSubmit={(e) => {
          e.preventDefault();
          send({ text }, "form");
        }}
      >
        <Field label={t("vehicle.type_instead")}>
          <textarea
            ref={area}
            rows="3"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t("vehicle.type_ph")}
            required
          />
        </Field>
        <button className="primary" disabled={busy}>
          {busy ? t("vehicle.thinking") : mode === "log" ? t("vehicle.add_note") : t("cop.send")}
        </button>
      </form>
      {unread ? (
        <p className="card bad" role="alert">
          {t("vehicle.unread")}
        </p>
      ) : failed ? (
        <p className="card bad" role="alert">
          {t("vehicle.failed")}
        </p>
      ) : err?.status === 503 ? (
        <p className="card bad" role="alert">
          {t("vehicle.busy")}
        </p>
      ) : (
        <Err e={err} />
      )}
      {res && (
        <div className="card">
          {shot ? (
            <div className="photo-res">
              <img className="thumb" src={shot} alt={t("vehicle.monitor_photo")} />
              <div>
                <div className="muted">{t("vehicle.read_from_monitor")}</div>
                <Fields fields={res.fields} photo />
              </div>
            </div>
          ) : (
            <>
              <div className="muted">{t("vehicle.transcript")}</div>
              <p className="quote">{res.transcript_en ?? "—"}</p>
              <div className="muted">{t("vehicle.extracted")}</div>
              <Fields fields={res.fields} transcript={res.transcript_en} />
            </>
          )}
          <Chips items={res.interventions} />
          {res.log ? (
            <p className="muted">{t("vehicle.added")}</p>
          ) : (
            <>
              <div className="muted">{t("vehicle.suggested")}</div>
              <div className={"big tier-" + tier}>{up}</div>
              <div className="muted">{t("vehicle.crew_confirms")}</div>
              <button
                className={"primary t-" + tier}
                disabled={confirming || confirmed === tier}
                onClick={confirm}
              >
                {confirming
                  ? t("vehicle.confirming")
                  : confirmed === tier
                    ? t("vehicle.confirmed", { tier: up })
                    : t("vehicle.confirm", { tier: up })}
              </button>
              <Err e={cerr} />
            </>
          )}
        </div>
      )}
    </section>
  );
}

function Log({ runId }) {
  const { rows, error } = useLog(runId);
  return (
    <section>
      <h2>{t("vehicle.log_h")}</h2>
      {error ? (
        <p className="card bad" role="alert">
          {t("common.load_failed", { what: t("what.log"), error })}
        </p>
      ) : !rows ? (
        <p className="muted">{t("common.loading")}</p>
      ) : !rows.length ? (
        <p className="muted">{t("vehicle.no_notes")}</p>
      ) : (
        <ul className="list">
          {rows.map((e) => (
            <li key={e.id}>
              <span className="muted">{when(e.t)}</span>
              <span className="pill">{e.kind === "form" ? t("vehicle.k_text") : e.kind}</span>
              <Thumb url={e.photo_url} />
              <div>{e.transcript_en ?? "—"}</div>
              <Chips items={e.interventions} />
              <div className="muted">
                {flat(e.fields)
                  .map(([k, v]) => `${k} ${show(v)}`)
                  .join(" · ")}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// The newest cop report on any of this run's alerts (alerts/{n}.cop_note), e.g. a stalled bus.
function CopNote({ runId }) {
  const [alerts, setAlerts] = useState([]);
  useEffect(() => {
    setAlerts([]);
    return onSnapshot(
      collection(db, `runs/${runId}/alerts`),
      (q) => setAlerts(q.docs.map((d) => d.data())),
      () => {},
    );
  }, [runId]);
  const a = currentAlert(
    alerts.filter((x) => x.cop_note),
    null,
  );
  return a ? (
    <p className="card" role="status">
      {copNoteText(a.cop_note, a.junction_id)}
    </p>
  ) : null;
}

function Run({ bound }) {
  const [incident, setIncident] = useState(store.get("incident_id") ?? "");
  const [corridor, setCorridor] = useState(store.get("corridor") ?? "blr");
  const [runId, setRunId] = useState(store.get("run_id"));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [ended, setEnded] = useState(null);
  const [noOpen, setNoOpen] = useState(false);
  const [badInc, setBadInc] = useState(null); // inline problem with the incident field
  const incRef = useRef(null);
  const [done, setDone] = useState(null); // confirm response, so the tier shows even if the run listener is down
  const run = useDoc(runId ? `runs/${runId}` : null);
  const hospital = corridors[corridor].hospital;
  const active = !!runId && run.data?.state !== "ended";
  const gps = useGps(runId, active);
  // focus order: plate (autofocus) -> bind -> incident ID, as soon as a vehicle is bound and no run is going
  useEffect(() => {
    if (bound && !runId) incRef.current?.focus();
  }, [bound?.plate]); // eslint-disable-line react-hooks/exhaustive-deps

  async function useLatest() {
    setNoOpen(false);
    setBadInc(null);
    try {
      const q = await getDocs(
        query(collection(db, "incidents"), orderBy("created_at", "desc"), limit(10)),
      );
      const i = latestOpen(q.docs.map((d) => ({ id: d.id, ...d.data() })));
      i ? setIncident(i.id) : setNoOpen(true);
    } catch (x) {
      setErr(x);
    }
  }
  async function start(e) {
    e.preventDefault();
    const id = incident.trim().toUpperCase();
    if (!INCIDENT_RE.test(id)) {
      setBadInc(t("vehicle.incident_bad"));
      return incRef.current?.focus();
    }
    setBadInc(null);
    setBusy(true);
    setErr(null);
    setEnded(null);
    setDone(null);
    store.set("incident_id", id);
    store.set("corridor", corridor);
    try {
      const r = await api("/runs", {
        action: "start",
        plate: bound.plate,
        incident_id: id,
        corridor,
        destination: { name: hospital.name, lat: hospital.lat, lng: hospital.lng },
        source: "gps",
      });
      store.set("run_id", r.run_id);
      setRunId(r.run_id);
    } catch (x) {
      setErr(x);
    }
    setBusy(false);
  }
  async function end() {
    setBusy(true);
    setErr(null);
    try {
      await api("/runs", { action: "end", run_id: runId });
      setEnded(runId);
      store.set("run_id", null);
      setRunId(null);
    } catch (x) {
      setErr(x);
    }
    setBusy(false);
  }

  const r = run.data;
  const confirmed = r?.confirmed_tier ?? done;
  return (
    <>
      <section>
        <h2>{t("vehicle.run_h")}</h2>
        {!bound ? (
          <p className="muted">{t("vehicle.bind_first")}</p>
        ) : runId ? (
          <>
            <div className="card">
              <div className={"tierpill " + (confirmed ? "t-" + confirmed : "")}>
                {confirmed ? tierLabel(confirmed).toUpperCase() : t("vehicle.tier_unconfirmed")}
              </div>
              <div className="muted">{t("vehicle.run", { id: runId })}</div>
              {run.loading && <p>{t("vehicle.loading_run")}</p>}
              {run.error && (
                <p className="bad" role="alert">
                  {t("common.load_failed", { what: t("what.run"), error: run.error })}
                </p>
              )}
              {run.missing && <p>{t("vehicle.run_missing")}</p>}
              {r && (
                <>
                  <div className="big">{r.state}</div>
                  <p>
                    {t("vehicle.run_line", {
                      plate: r.vehicle_plate,
                      incident: r.incident_id,
                      dest: r.destination?.name ?? "—",
                    })}
                  </p>
                  {r.state === "arrived" ? (
                    <p>{t("vehicle.eta_arrived")}</p>
                  ) : (
                    r.eta_hospital_s != null && (
                      <p>{t("vehicle.eta", { n: Math.round(r.eta_hospital_s / 60) })}</p>
                    )
                  )}
                </>
              )}
              <CopNote runId={runId} />
              <p className="muted">{gps}</p>
              <button className="danger" disabled={busy} onClick={end}>
                {busy ? t("vehicle.ending") : t("vehicle.end")}
              </button>
            </div>
            <TraceCard routing={r?.routing} pending={!!confirmed && bound?.type === "ambulance"} />
          </>
        ) : (
          <form className="card" onSubmit={start} noValidate>
            <Field
              label={t("vehicle.incident")}
              error={badInc ?? (noOpen ? t("vehicle.no_open") : null)}
            >
              <input
                ref={incRef}
                value={incident}
                onChange={(e) => setIncident(e.target.value)}
                placeholder="INC-4BC6E7"
                autoCapitalize="characters"
                autoComplete="off"
                autoCorrect="off"
                spellCheck={false}
                enterKeyHint="go"
                required
              />
            </Field>
            <button type="button" onClick={useLatest} disabled={busy}>
              {t("vehicle.use_latest")}
            </button>
            <Field label={t("cop.corridor")}>
              <select value={corridor} onChange={(e) => setCorridor(e.target.value)}>
                {Object.values(corridors).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.id} · {c.name}
                  </option>
                ))}
              </select>
            </Field>
            <p className="muted">{t("vehicle.destination", { name: hospital.name })}</p>
            <button className="primary" disabled={busy}>
              {busy ? t("vehicle.starting") : t("vehicle.start")}
            </button>
          </form>
        )}
        {ended && (
          <p className="card good" role="status">
            {t("vehicle.ended", { id: ended })}
          </p>
        )}
        {err?.status === 403 || err?.status === 401 ? (
          <p className="card reject" role="alert">
            {err.message === "no_active_incident"
              ? t("vehicle.err_incident")
              : err.message.startsWith("device_token")
                ? t("vehicle.err_token")
                : t("vehicle.err_unreg")}
          </p>
        ) : (
          <Err e={err} />
        )}
      </section>
      {runId && (
        <Triage
          key={runId}
          runId={runId}
          vehicleType={bound?.type}
          confirmed={confirmed}
          setDone={setDone}
        />
      )}
      {runId && <Log runId={runId} />}
    </>
  );
}

export default function Vehicle() {
  const [bound, setBound] = useState(() => {
    try {
      return JSON.parse(store.get("bound"));
    } catch {
      return null;
    }
  });
  return (
    <>
      <Coach role="vehicle" />
      <Bind bound={bound} setBound={setBound} />
      <Run bound={bound} />
      <LastRouting />
    </>
  );
}
