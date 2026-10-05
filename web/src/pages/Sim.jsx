import { useEffect, useRef, useState } from "react";
import { corridors, scenario } from "../data.js";
import { startFeed } from "../feeder.js";
import { useActiveRuns, useAlerts, useJunctions } from "../live.js";
import CorridorMap from "../map.jsx";
import "../sim.css";

const scenarios = { example: scenario }; // ponytail: one scenario for now
const dash = (v, f = (x) => x) => (v == null || v === "" ? "—" : f(v));
const tierOf = (r) => r.confirmed_tier ?? r.acuity_tier;

// recorded_spans is {junction: [{ts, intervals}]}; pick the snapshot in force at scenario time t.
function spansAt(rec, t) {
  return Object.fromEntries(Object.entries(rec ?? {}).map(([k, snaps]) => {
    const t0 = Date.parse(snaps[0].ts);
    return [k, (snaps.findLast((s) => (Date.parse(s.ts) - t0) / 1000 <= t) ?? snaps[0]).intervals];
  }));
}

function Alerts({ rows, mode }) {
  return (
    <div className="alerts" title={mode === "per-run" ? "per-run reads (collectionGroup index missing)" : undefined}>
      {rows.length === 0 && <span className="muted">No alerts yet.</span>}
      {rows.map((a) => (
        <div key={`${a.run_id}/${a.id}`} className="alert">
          <b className={`stage s-${a.stage}`}>{dash(a.stage)}</b>
          <span>{dash(a.text, (t) => t)}</span>
        </div>
      ))}
    </div>
  );
}

export default function Sim() {
  const [cid, setCid] = useState(() => { const c = new URLSearchParams(location.search).get("corridor"); return corridors[c] ? c : "blr"; });
  const corridor = corridors[cid];
  const junctions = useJunctions(cid);
  const runs = useActiveRuns(cid);
  const alerts = useAlerts(runs.map((r) => r.id).sort());
  const pickCorridor = (c) => {
    setCid(c);
    history.replaceState(null, "", `?corridor=${c}`);
  };

  const [scn, setScn] = useState("example");
  const sc = scenarios[scn];
  const [idx, setIdx] = useState(0);
  const v = sc.vehicles[idx];
  const [runId, setRunId] = useState(v.run_id);
  const [speed, setSpeed] = useState(1);
  const [prog, setProg] = useState(null);
  const [running, setRunning] = useState(false);
  const stop = useRef(null);
  useEffect(() => () => stop.current?.(), []);

  const pick = (i) => { setIdx(i); setRunId(sc.vehicles[i].run_id); };
  const start = () => {
    setRunning(true); setProg(null);
    stop.current = startFeed({ vehicle: v, runId, speed, onTick: setProg, onDone: () => setRunning(false) });
  };
  const halt = () => { stop.current?.(); setRunning(false); };

  // vehicles at their last tick; the feeder's own position fills in until the backend writes ticks[]
  const vehicles = runs.map((r) => {
    const k = r.ticks?.at(-1);
    return { id: r.id, type: r.vehicle_type, lat: k?.lat ?? r.lat, lng: k?.lng ?? r.lng };
  }).filter((x) => Number.isFinite(x.lat));
  if (prog && !vehicles.some((x) => x.id === runId)) {
    const k = v.ticks[prog.i - 1];
    vehicles.push({ id: runId, type: v.type, lat: k.lat, lng: k.lng });
  }
  const spans = running && sc.corridor === cid ? spansAt(sc.recorded_spans, prog?.t ?? 0) : undefined;
  const stageOf = (r) => r.stage ?? alerts.rows.find((a) => a.run_id === r.id)?.stage;

  return (
    <div className="sim">
      <Alerts {...alerts} />
      <div className="simgrid">
        <div className="simmap"><CorridorMap corridor={corridor} junctions={junctions} vehicles={vehicles} spans={spans} /></div>
        <div className="simpanel">
          <section className="card">
            <label>Corridor
              <select value={cid} onChange={(e) => pickCorridor(e.target.value)}>
                {Object.values(corridors).map((c) => <option key={c.id} value={c.id}>{c.id} · {c.name}</option>)}
              </select>
            </label>
            <h2>Active runs ({runs.length})</h2>
            {runs.length === 0 && <p className="muted">None. Start a run on /vehicle or feed one below.</p>}
            {runs.map((r) => (
              <div key={r.id} className="run">
                <div><b>{r.vehicle_plate ?? r.id}</b> <span className="muted">{dash(r.vehicle_type)}</span>
                  <span className={`tp t-${tierOf(r)}`}>{dash(tierOf(r))}</span></div>
                <dl>
                  <dt>Next</dt><dd>{dash(r.next_junction_id)}</dd>
                  <dt>ETA</dt><dd>{dash(r.eta_s, (s) => `${s} s`)}</dd>
                  <dt>Stage</dt><dd>{dash(stageOf(r))}</dd>
                  <dt>State</dt><dd>{dash(r.state)}</dd>
                </dl>
              </div>
            ))}
          </section>
          <section className="card">
            <h2>GPS feeder</h2>
            <label>Scenario
              <select value={scn} disabled={running} onChange={(e) => { setScn(e.target.value); setIdx(0); setRunId(scenarios[e.target.value].vehicles[0].run_id); }}>
                {Object.keys(scenarios).map((k) => <option key={k} value={k}>Scenario: {k}</option>)}
              </select>
            </label>
            {sc.corridor !== cid && <p className="muted">This scenario is for {sc.corridor}; select that corridor to see its spans.</p>}
            <label>Vehicle
              <select value={idx} disabled={running} onChange={(e) => pick(+e.target.value)}>
                {sc.vehicles.map((x, i) => <option key={x.run_id} value={i}>{x.plate} · {x.type} · {x.ticks.length} ticks</option>)}
              </select>
            </label>
            <label>Run ID (start a run on /vehicle first, or use the scenario's)
              <input value={runId} disabled={running} onChange={(e) => setRunId(e.target.value)} />
            </label>
            <div className="row">
              {[1, 5].map((s) => (
                <button key={s} className={speed === s ? "primary" : ""} disabled={running} onClick={() => setSpeed(s)}>{s}x</button>
              ))}
            </div>
            {running ? <button className="danger" onClick={halt}>Stop</button> : <button className="primary" onClick={start}>Start</button>}
            <p className="muted">
              {prog
                ? `Tick ${prog.i}/${prog.n} · t=${prog.t}s · last response: ${prog.status}${prog.i === prog.n && !running ? " · done" : ""}`
                : running ? "Sending first tick…" : "Idle."}
            </p>
            {prog && prog.status !== 200 && <p className="muted">501 is expected until /location is implemented; the feed keeps going.</p>}
          </section>
        </div>
      </div>
    </div>
  );
}
