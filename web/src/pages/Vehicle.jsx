import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { corridors } from "../data.js";
import { Err, deviceId, store, useDoc } from "../ui.jsx";

function Bind({ bound, setBound }) {
  const [plate, setPlate] = useState(store.get("plate") ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function submit(e) {
    e.preventDefault();
    const p = plate.trim().toUpperCase();
    setBusy(true); setErr(null); setBound(null);
    store.set("plate", p);
    try {
      const r = await api("/vehicles/bind", { plate: p, device_id: deviceId() });
      store.set("bound", JSON.stringify(r));
      setBound(r);
    } catch (x) { store.set("bound", null); setErr(x); }
    setBusy(false);
  }

  return (
    <section>
      <h2>1. Bind this device</h2>
      <form className="card" onSubmit={submit}>
        <label>Vehicle plate
          <input value={plate} onChange={(e) => setPlate(e.target.value)} placeholder="KA01AB1234" autoCapitalize="characters" required />
        </label>
        <button className="primary" disabled={busy}>{busy ? "Binding…" : "Bind"}</button>
      </form>
      {err?.status === 404 ? (
        <div className="card reject"><div className="big">Unregistered vehicle</div>
          <p>{plate.trim().toUpperCase()} is not in the registry, or is inactive. No run can start.</p></div>
      ) : <Err e={err} />}
      {bound && (
        <div className="card good">
          <div className="big">{bound.plate} bound</div>
          <p>Type: <b>{bound.type}</b> · Agency: <b>{bound.agency}</b></p>
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
    if (!navigator.geolocation) { setNote("GPS not available on this device."); return; }
    setNote("Waiting for GPS…");
    const id = navigator.geolocation.watchPosition(
      async (p) => {
        if (Date.now() - last.current < 5000) return;
        last.current = Date.now();
        const c = p.coords;
        try {
          await api("/location", {
            run_id: runId, lat: c.latitude, lng: c.longitude, speed_mps: c.speed ?? 0,
            heading: c.heading, t: new Date(p.timestamp).toISOString(), source: "gps",
          });
          setNote("GPS sent " + new Date().toLocaleTimeString());
        } catch (e) {
          if (e.status === 501) console.log("/location not implemented yet (501)");
          else { console.log("/location failed", e); setNote("GPS send failed: " + e.message); }
        }
      },
      (e) => setNote("GPS error: " + e.message),
      { enableHighAccuracy: true },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [runId, active]);
  return note;
}

function Triage({ runId, vehicleType, run }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [res, setRes] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [cerr, setCerr] = useState(null);
  const [done, setDone] = useState(null); // confirm response, so the tier shows even if the run listener is down

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setErr(null); setRes(null);
    try { setRes(await api("/triage", { run_id: runId, vehicle_type: vehicleType, text })); }
    catch (x) { setErr(x); }
    setBusy(false);
  }
  async function confirm() {
    setConfirming(true); setCerr(null);
    try { setDone((await api(`/runs/${runId}/confirm`, { tier: res.suggested_tier })).confirmed_tier); }
    catch (x) { setCerr(x); }
    setConfirming(false);
  }

  const confirmed = run?.confirmed_tier ?? done;
  return (
    <section>
      <h2>3. Patient</h2>
      <button className="giant" disabled>Hold to speak<small>coming soon</small></button>
      <form className="card" onSubmit={submit}>
        <label>Type instead
          <textarea rows="3" value={text} onChange={(e) => setText(e.target.value)} placeholder="chest pain, BP 85 over 50" required />
        </label>
        <button className="primary" disabled={busy}>{busy ? "Thinking…" : "Send"}</button>
      </form>
      {err?.body?.error === "extraction_failed"
        ? <p className="card bad">Couldn't understand, type it again with more detail.</p>
        : <Err e={err} />}
      {res && (
        <div className="card">
          <div className="muted">Transcript (English)</div>
          <p>{res.transcript_en ?? "—"}</p>
          <div className="muted">Fields</div>
          <pre>{JSON.stringify(res.fields, null, 2)}</pre>
          <div className="muted">Suggested tier</div>
          <div className={"big tier-" + res.suggested_tier}>{String(res.suggested_tier).toUpperCase()}</div>
          <button className="primary" disabled={confirming || confirmed === res.suggested_tier} onClick={confirm}>
            {confirming ? "Confirming…" : `Confirm ${String(res.suggested_tier).toUpperCase()}`}
          </button>
          <Err e={cerr} />
        </div>
      )}
      <div className="card">
        <div className="muted">Confirmed tier</div>
        {confirmed
          ? <div className={"big tier-" + confirmed}>{confirmed.toUpperCase()}</div>
          : <p>Not confirmed yet.</p>}
      </div>
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
  const run = useDoc(runId ? `runs/${runId}` : null);
  const hospital = corridors[corridor].hospital;
  const active = !!runId && run.data?.state !== "ended";
  const gps = useGps(runId, active);

  async function start(e) {
    e.preventDefault();
    setBusy(true); setErr(null); setEnded(null);
    const id = incident.trim().toUpperCase();
    store.set("incident_id", id); store.set("corridor", corridor);
    try {
      const r = await api("/runs", {
        action: "start", plate: bound.plate, incident_id: id, corridor,
        destination: { name: hospital.name, lat: hospital.lat, lng: hospital.lng }, source: "gps",
      });
      store.set("run_id", r.run_id); setRunId(r.run_id);
    } catch (x) { setErr(x); }
    setBusy(false);
  }
  async function end() {
    setBusy(true); setErr(null);
    try {
      await api("/runs", { action: "end", run_id: runId });
      setEnded(runId); store.set("run_id", null); setRunId(null);
    } catch (x) { setErr(x); }
    setBusy(false);
  }

  const r = run.data;
  return (
    <>
      <section>
        <h2>2. Start run</h2>
        {!bound ? <p className="muted">Bind a registered vehicle first.</p> : runId ? (
          <div className="card">
            <div className="muted">Run {runId}</div>
            {run.loading && <p>Loading run…</p>}
            {run.error && <p className="bad">Could not load run: {run.error}</p>}
            {run.missing && <p>Run document not found yet.</p>}
            {r && (
              <>
                <div className="big">{r.state}</div>
                <p>{r.vehicle_plate} · incident {r.incident_id} · to {r.destination?.name ?? "—"}</p>
                {r.eta_hospital_s != null && <p>Hospital ETA: {Math.round(r.eta_hospital_s / 60)} min</p>}
              </>
            )}
            <p className="muted">{gps}</p>
            <button className="danger" disabled={busy} onClick={end}>{busy ? "Ending…" : "End run"}</button>
          </div>
        ) : (
          <form className="card" onSubmit={start}>
            <label>Incident ID
              <input value={incident} onChange={(e) => setIncident(e.target.value)} placeholder="INC-4BC6E7" required />
            </label>
            <label>Corridor
              <select value={corridor} onChange={(e) => setCorridor(e.target.value)}>
                {Object.values(corridors).map((c) => <option key={c.id} value={c.id}>{c.id} · {c.name}</option>)}
              </select>
            </label>
            <p className="muted">Destination: {hospital.name}</p>
            <button className="primary" disabled={busy}>{busy ? "Starting…" : "Start run"}</button>
          </form>
        )}
        {ended && <p className="card good">Run {ended} ended.</p>}
        {err?.status === 403 ? (
          <p className="card reject">{err.message === "no_active_incident"
            ? "No active incident: that incident ID is unknown or not open."
            : "Unregistered vehicle: run refused."}</p>
        ) : <Err e={err} />}
      </section>
      {runId && <Triage runId={runId} vehicleType={bound?.type} run={r} />}
    </>
  );
}

export default function Vehicle() {
  const [bound, setBound] = useState(() => { try { return JSON.parse(store.get("bound")); } catch { return null; } });
  return (
    <>
      <Bind bound={bound} setBound={setBound} />
      <Run bound={bound} />
    </>
  );
}
