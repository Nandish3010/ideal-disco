import { useEffect, useRef, useState } from "react";
import { scenario } from "../data.js";
import { startFeed } from "../feeder.js";

export default function Sim() {
  const [idx, setIdx] = useState(0);
  const v = scenario.vehicles[idx];
  const [runId, setRunId] = useState(v.run_id);
  const [speed, setSpeed] = useState(1);
  const [prog, setProg] = useState(null);
  const [running, setRunning] = useState(false);
  const stop = useRef(null);
  useEffect(() => () => stop.current?.(), []);

  const pick = (i) => { setIdx(i); setRunId(scenario.vehicles[i].run_id); };
  const start = () => {
    setRunning(true); setProg(null);
    stop.current = startFeed({
      vehicle: v, runId, speed, onTick: setProg, onDone: () => setRunning(false),
    });
  };
  const halt = () => { stop.current?.(); setRunning(false); };

  return (
    <>
      <section className="card">
        <h2>GPS feeder</h2>
        <label>Vehicle
          <select value={idx} disabled={running} onChange={(e) => pick(+e.target.value)}>
            {scenario.vehicles.map((x, i) => <option key={x.run_id} value={i}>{x.plate} · {x.type} · {x.ticks.length} ticks</option>)}
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
      <p className="muted">Twin map and with-vs-without replay: placeholder.</p>
    </>
  );
}
