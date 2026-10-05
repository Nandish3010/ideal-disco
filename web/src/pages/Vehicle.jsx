import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { corridors } from "../data.js";
import { TraceCard } from "../trace.jsx";
import { Err, deviceId, store, useDoc, useLog, when } from "../ui.jsx";

function Bind({ bound, setBound }) {
  const [plate, setPlate] = useState(store.get("plate") ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function submit(e) {
    e.preventDefault();
    const p = plate.trim().toUpperCase();
    setBusy(true);
    setErr(null);
    setBound(null);
    store.set("plate", p);
    try {
      const r = await api("/vehicles/bind", { plate: p, device_id: deviceId() });
      store.set("bound", JSON.stringify(r));
      setBound(r);
    } catch (x) {
      store.set("bound", null);
      setErr(x);
    }
    setBusy(false);
  }

  return (
    <section>
      <h2>1. Bind this device</h2>
      <form className="card" onSubmit={submit}>
        <label>
          Vehicle plate
          <input
            value={plate}
            onChange={(e) => setPlate(e.target.value)}
            placeholder="KA01AB1234"
            autoCapitalize="characters"
            required
          />
        </label>
        <button className="primary" disabled={busy}>
          {busy ? "Binding…" : "Bind"}
        </button>
      </form>
      {err?.status === 404 ? (
        <div className="card reject">
          <div className="big">Unregistered vehicle</div>
          <p>
            {plate.trim().toUpperCase()} is not in the registry, or is inactive. No run can start.
          </p>
        </div>
      ) : (
        <Err e={err} />
      )}
      {bound && (
        <div className="card good">
          <div className="big">{bound.plate} bound</div>
          <p>
            Type: <b>{bound.type}</b> · Agency: <b>{bound.agency}</b>
          </p>
        </div>
      )}
    </section>
  );
}

// Posts position to /location at most every 5 s while a run is active. The 501 stub is logged, not shown.
function useGps(runId, active) {
  const [note, setNote] = useState("");
  const last = useRef(0);
  useEffect(() => {
    if (!active || !runId) return;
    if (!navigator.geolocation) {
      setNote("GPS not available on this device.");
      return;
    }
    setNote("Waiting for GPS…");
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
          setNote("GPS sent " + new Date().toLocaleTimeString());
        } catch (e) {
          if (e.status === 501) console.log("/location not implemented yet (501)");
          else {
            console.log("/location failed", e);
            setNote("GPS send failed: " + e.message);
          }
        }
      },
      (e) => setNote("GPS error: " + e.message),
      { enableHighAccuracy: true },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [runId, active]);
  return note;
}

const MAX_S = 20;
const b64 = (blob) =>
  new Promise((ok, no) => {
    const f = new FileReader();
    f.onload = () => ok(f.result.split(",")[1]);
    f.onerror = no;
    f.readAsDataURL(blob);
  });
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

// Press-and-hold recorder. onClip(blob) on release, onClip(null) when the hold was too short.
function useHold(onClip) {
  const [st, setSt] = useState({ on: false, s: 0 });
  const [mic, setMic] = useState(null); // "denied" | "unavailable"
  const x = useRef({});
  x.current.onClip = onClip;

  async function start() {
    const c = x.current;
    if (c.rec || c.starting) return;
    c.held = true;
    c.starting = true;
    let stream;
    try {
      if (!window.MediaRecorder || !navigator.mediaDevices?.getUserMedia)
        throw new Error("unsupported");
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      c.starting = false;
      c.held = false;
      setMic(e.name === "NotAllowedError" || e.name === "SecurityError" ? "denied" : "unavailable");
      return;
    }
    c.starting = false;
    setMic(null);
    if (!c.held) {
      stream.getTracks().forEach((t) => t.stop());
      return;
    } // released before the mic opened
    const type = ["audio/webm;codecs=opus", "audio/mp4"].find((t) =>
      MediaRecorder.isTypeSupported(t),
    );
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks = [];
    const t0 = Date.now();
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = () => {
      clearInterval(c.tick);
      stream.getTracks().forEach((t) => t.stop());
      c.rec = null;
      setSt({ on: false, s: 0 });
      c.onClip(Date.now() - t0 < 600 ? null : new Blob(chunks, { type: rec.mimeType }));
    };
    c.rec = rec;
    rec.start();
    setSt({ on: true, s: 0 });
    c.tick = setInterval(() => {
      const s = (Date.now() - t0) / 1000;
      setSt({ on: true, s });
      if (s >= MAX_S) stop();
    }, 100);
  }
  function stop() {
    const c = x.current;
    c.held = false;
    if (c.rec?.state === "recording") c.rec.stop();
  }
  useEffect(
    () => () => {
      stop();
      clearInterval(x.current.tick);
    },
    [],
  );
  return { ...st, mic, start, stop };
}

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
      <img className="thumb" src={url} alt="Monitor photo" loading="lazy" />
    </a>
  ) : null;

function Fields({ fields, transcript, photo }) {
  const rows = flat(fields);
  if (!rows.length) return <p className="muted">No fields extracted.</p>;
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
                {photo ? "from photo" : ok ? "in transcript" : "inferred"}
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
      return setNote("Couldn't open that photo, type it instead.");
    }
    send({ image_b64: r.b64, mime: "image/jpeg" }, "photo", r.url);
  }
  const hold = useHold(async (blob) => {
    if (!blob) return setNote("Too short. Hold the button while you speak.");
    setBusy(true);
    send({ audio_b64: await b64(blob), mime: blob.type.split(";")[0] || "audio/webm" }, "voice");
  });
  const failed = err?.body?.error === "extraction_failed";
  // 422 = unreadable; 400/501 = backend without image support yet
  const unread = shot && [400, 422, 501].includes(err?.status);
  useEffect(() => {
    if (failed || unread || hold.mic) area.current?.focus();
  }, [failed, unread, hold.mic]);

  const tier = res?.suggested_tier;
  const up = String(tier).toUpperCase();
  return (
    <section>
      <h2>3. Patient</h2>
      <div className="row" role="group" aria-label="Note type">
        {[
          ["triage", "Triage"],
          ["log", "Log note"],
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
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture?.(e.pointerId);
          hold.start();
        }}
        onPointerUp={hold.stop}
        onPointerCancel={hold.stop}
        onBlur={hold.stop}
        onKeyDown={(e) => {
          if ((e.key === " " || e.key === "Enter") && !e.repeat) {
            e.preventDefault();
            hold.start();
          }
        }}
        onKeyUp={(e) => {
          if (e.key === " " || e.key === "Enter") hold.stop();
        }}
        onContextMenu={(e) => e.preventDefault()}
      >
        {busy
          ? shot
            ? "Reading the monitor…"
            : "Thinking…"
          : hold.on
            ? `Listening ${clock(hold.s)}`
            : "Hold to speak"}
        {hold.on && (
          <small>
            {Math.max(0, Math.ceil(MAX_S - hold.s))} s left
            <span className="meter">
              <i style={{ width: Math.min(100, (hold.s / MAX_S) * 100) + "%" }} />
            </span>
          </small>
        )}
      </button>
      <label className={"btn photo" + (busy ? " off" : "")}>
        {busy && shot ? "Reading the monitor…" : "📷 Monitor photo"}
        <input
          type="file"
          accept="image/*"
          capture="environment"
          disabled={busy}
          onChange={photo}
          hidden
        />
      </label>
      {note && <p className="muted">{note}</p>}
      {hold.mic && (
        <p className="card bad">
          {hold.mic === "denied"
            ? "Microphone is blocked for this site."
            : "Voice recording is not available on this device."}{" "}
          Type it below instead.
        </p>
      )}
      <form
        className="card"
        onSubmit={(e) => {
          e.preventDefault();
          send({ text }, "form");
        }}
      >
        <label>
          Type instead
          <textarea
            ref={area}
            rows="3"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="chest pain, BP 85 over 50"
            required
          />
        </label>
        <button className="primary" disabled={busy}>
          {busy ? "Thinking…" : mode === "log" ? "Add note" : "Send"}
        </button>
      </form>
      {unread ? (
        <p className="card bad">Couldn&apos;t read the screen, type it instead.</p>
      ) : failed ? (
        <p className="card bad">
          Couldn&apos;t understand, type it. Add more detail in the box above.
        </p>
      ) : err?.status === 503 ? (
        <p className="card bad">Service busy, try again.</p>
      ) : (
        <Err e={err} />
      )}
      {res && (
        <div className="card">
          {shot ? (
            <div className="photo-res">
              <img className="thumb" src={shot} alt="Monitor photo" />
              <div>
                <div className="muted">Read from the monitor</div>
                <Fields fields={res.fields} photo />
              </div>
            </div>
          ) : (
            <>
              <div className="muted">Transcript (English)</div>
              <p className="quote">{res.transcript_en ?? "—"}</p>
              <div className="muted">Extracted from the transcript</div>
              <Fields fields={res.fields} transcript={res.transcript_en} />
            </>
          )}
          <Chips items={res.interventions} />
          {res.log ? (
            <p className="muted">Added to the transit log.</p>
          ) : (
            <>
              <div className="muted">Suggested tier</div>
              <div className={"big tier-" + tier}>{up}</div>
              <div className="muted">Crew confirms</div>
              <button
                className={"primary t-" + tier}
                disabled={confirming || confirmed === tier}
                onClick={confirm}
              >
                {confirming
                  ? "Confirming…"
                  : confirmed === tier
                    ? `Confirmed ${up}`
                    : `Confirm ${up}`}
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
      <h2>4. Transit log</h2>
      {error ? (
        <p className="card bad">Could not load log: {error}</p>
      ) : !rows ? (
        <p className="muted">Loading…</p>
      ) : !rows.length ? (
        <p className="muted">No notes yet</p>
      ) : (
        <ul className="list">
          {rows.map((e) => (
            <li key={e.id}>
              <span className="muted">{when(e.t)}</span>
              <span className="pill">{e.kind === "form" ? "text" : e.kind}</span>
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

function Run({ bound }) {
  const [incident, setIncident] = useState(store.get("incident_id") ?? "");
  const [corridor, setCorridor] = useState(store.get("corridor") ?? "blr");
  const [runId, setRunId] = useState(store.get("run_id"));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [ended, setEnded] = useState(null);
  const [done, setDone] = useState(null); // confirm response, so the tier shows even if the run listener is down
  const run = useDoc(runId ? `runs/${runId}` : null);
  const hospital = corridors[corridor].hospital;
  const active = !!runId && run.data?.state !== "ended";
  const gps = useGps(runId, active);

  async function start(e) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setEnded(null);
    setDone(null);
    const id = incident.trim().toUpperCase();
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
        <h2>2. Start run</h2>
        {!bound ? (
          <p className="muted">Bind a registered vehicle first.</p>
        ) : runId ? (
          <>
            <div className="card">
              <div className={"tierpill " + (confirmed ? "t-" + confirmed : "")}>
                {confirmed ? confirmed.toUpperCase() : "Tier not confirmed"}
              </div>
              <div className="muted">Run {runId}</div>
              {run.loading && <p>Loading run…</p>}
              {run.error && <p className="bad">Could not load run: {run.error}</p>}
              {run.missing && <p>Run document not found yet.</p>}
              {r && (
                <>
                  <div className="big">{r.state}</div>
                  <p>
                    {r.vehicle_plate} · incident {r.incident_id} · to {r.destination?.name ?? "—"}
                  </p>
                  {r.eta_hospital_s != null && (
                    <p>Hospital ETA: {Math.round(r.eta_hospital_s / 60)} min</p>
                  )}
                </>
              )}
              <p className="muted">{gps}</p>
              <button className="danger" disabled={busy} onClick={end}>
                {busy ? "Ending…" : "End run"}
              </button>
            </div>
            <TraceCard routing={r?.routing} pending={!!confirmed && bound?.type === "ambulance"} />
          </>
        ) : (
          <form className="card" onSubmit={start}>
            <label>
              Incident ID
              <input
                value={incident}
                onChange={(e) => setIncident(e.target.value)}
                placeholder="INC-4BC6E7"
                required
              />
            </label>
            <label>
              Corridor
              <select value={corridor} onChange={(e) => setCorridor(e.target.value)}>
                {Object.values(corridors).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.id} · {c.name}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted">Destination: {hospital.name}</p>
            <button className="primary" disabled={busy}>
              {busy ? "Starting…" : "Start run"}
            </button>
          </form>
        )}
        {ended && <p className="card good">Run {ended} ended.</p>}
        {err?.status === 403 ? (
          <p className="card reject">
            {err.message === "no_active_incident"
              ? "No active incident: that incident ID is unknown or not open."
              : "Unregistered vehicle: run refused."}
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
      <Bind bound={bound} setBound={setBound} />
      <Run bound={bound} />
    </>
  );
}
