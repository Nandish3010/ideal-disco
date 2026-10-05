import { useEffect, useMemo, useRef, useState } from "react";
import { corridors, scenario } from "../data.js";
import blrTwoVehicles from "../../../data/scenarios/blr-two-vehicles.json";
import { api } from "../api.js";
import { startFeed, startFeedAll } from "../feeder.js";
import { useActiveRuns, useAlerts, useJunctions } from "../live.js";
import CorridorMap from "../map.jsx";
import { at, savedAt, simulate, spansAt, stage } from "../replay.js";
import "../sim.css";

const scenarios = { example: scenario, "blr-two-vehicles": blrTwoVehicles };
const dash = (v, f = (x) => x) => (v == null || v === "" ? "—" : f(v));
const tierOf = (r) => r.confirmed_tier ?? r.acuity_tier;
const mmss = (s) => { s = Math.round(s); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

// scenario vehicle -> run id, kept per scenario in localStorage (the "Create runs" button writes it)
const storeKey = (scn) => `sim.runs.${scn}`;
const loadRuns = (scn) => { try { return JSON.parse(localStorage.getItem(storeKey(scn))) ?? {}; } catch { return {}; } };
const saveRuns = (scn, m) => { try { localStorage.setItem(storeKey(scn), JSON.stringify(m)); } catch { /* private mode */ } };

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

function ScenarioSelect({ value, onChange, disabled }) {
  return (
    <label>Scenario
      <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {Object.keys(scenarios).map((k) => <option key={k} value={k}>Scenario: {k}</option>)}
      </select>
    </label>
  );
}

// ---------------- Live: Firestore twin + GPS feeder ----------------
function Live({ scn, setScn }) {
  const [cid, setCid] = useState(() => { const c = new URLSearchParams(location.search).get("corridor"); return corridors[c] ? c : "blr"; });
  const corridor = corridors[cid];
  const junctions = useJunctions(cid);
  const runs = useActiveRuns(cid);
  const alerts = useAlerts(runs.map((r) => r.id).sort());
  const pickCorridor = (c) => {
    setCid(c);
    history.replaceState(null, "", `?corridor=${c}`);
  };

  const sc = scenarios[scn];
  const [idx, setIdx] = useState(0);
  const v = sc.vehicles[idx];
  const [map, setMap] = useState(() => loadRuns(scn));
  const [runId, setRunId] = useState(() => map[v.plate] ?? v.run_id);
  const [all, setAll] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [progs, setProgs] = useState({}); // {plate: {i, n, t, status}}
  const [fed, setFed] = useState({}); // {plate: run id being fed}
  const [running, setRunning] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState(null);
  const stop = useRef(null);
  useEffect(() => () => stop.current?.(), []);

  const pickScn = (k) => { setScn(k); setIdx(0); setMap(loadRuns(k)); setRunId(loadRuns(k)[scenarios[k].vehicles[0].plate] ?? scenarios[k].vehicles[0].run_id); setCreateErr(null); };
  const pick = (i) => { setIdx(i); setRunId(map[sc.vehicles[i].plate] ?? sc.vehicles[i].run_id); };

  const start = () => {
    setRunning(true); setProgs({});
    const onTick = (p) => setProgs((s) => ({ ...s, [p.plate ?? v.plate]: p }));
    const onDone = () => setRunning(false);
    if (all) {
      const ids = Object.fromEntries(sc.vehicles.map((x) => [x.plate, map[x.plate] ?? x.run_id]));
      setFed(ids);
      stop.current = startFeedAll({ scenario: sc, runIds: ids, speed, onTick, onDone });
    } else {
      setFed({ [v.plate]: runId });
      stop.current = startFeed({ vehicle: v, runId, speed, onTick, onDone });
    }
  };
  const halt = () => { stop.current?.(); setRunning(false); };

  // Every scenario vehicle gets its own incident and run so /location has something to attach to.
  const createRuns = async () => {
    setCreating(true); setCreateErr(null);
    const m = { ...map };
    try {
      for (const x of sc.vehicles) {
        try {
          const { incident_id } = await api("/incidents", { type: x.type === "fire" ? "fire" : "medical", severity_note: `Scenario ${scn} (synthetic)` });
          const { run_id } = await api("/runs", { action: "start", plate: x.plate, incident_id, corridor: sc.corridor, destination: corridors[sc.corridor]?.hospital, source: "sim" });
          m[x.plate] = run_id;
          // the crew's one tap: priority only reads confirmed_tier (fire vehicles carry their tier on the run, no confirm)
          if (x.type !== "fire" && x.tier) await api(`/runs/${run_id}/confirm`, { tier: x.tier });
        } catch (e) {
          throw Object.assign(e, { plate: x.plate });
        }
      }
    } catch (e) {
      setCreateErr(`${e.plate}: ${e.message}${e.status ? ` (HTTP ${e.status})` : ""}${e.body?.detail ? ` ${JSON.stringify(e.body.detail)}` : ""}`);
    }
    setMap(m); saveRuns(scn, m);
    setRunId(m[v.plate] ?? v.run_id);
    setCreating(false);
  };

  // vehicles at their last tick; the feeder's own position fills in until the backend writes ticks[]
  const vehicles = runs.map((r) => {
    const k = r.ticks?.at(-1);
    return { id: r.id, type: r.vehicle_type, lat: k?.lat ?? r.lat, lng: k?.lng ?? r.lng };
  }).filter((x) => Number.isFinite(x.lat));
  for (const x of sc.vehicles) {
    const p = progs[x.plate];
    if (p && fed[x.plate] && !vehicles.some((y) => y.id === fed[x.plate])) {
      const k = x.ticks[p.i - 1];
      vehicles.push({ id: fed[x.plate], type: x.type, lat: k.lat, lng: k.lng });
    }
  }
  // scenario clock for the recorded spans: latest tick time, plus the start offset when everyone runs together
  const tNow = Math.max(0, ...sc.vehicles.map((x) => (progs[x.plate] ? (all ? x.start_offset_s ?? 0 : 0) + progs[x.plate].t : 0)));
  const spans = running && sc.corridor === cid ? spansAt(sc.recorded_spans, tNow) : undefined;
  const stageOf = (r) => r.stage ?? alerts.rows.find((a) => a.run_id === r.id)?.stage;
  const seen = sc.vehicles.filter((x) => progs[x.plate]);

  return (
    <>
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
            <ScenarioSelect value={scn} disabled={running} onChange={pickScn} />
            {sc.corridor !== cid && <p className="muted">This scenario is for {sc.corridor}; select that corridor to see its spans.</p>}
            <div className="row">
              <button className={!all ? "on" : ""} disabled={running} onClick={() => setAll(false)}>One vehicle</button>
              <button className={all ? "on" : ""} disabled={running} onClick={() => setAll(true)}>All vehicles</button>
            </div>
            {all ? (
              <p className="muted">Runs every vehicle with its start offset ({sc.vehicles.map((x) => `${x.plate} +${x.start_offset_s ?? 0} s`).join(", ")}).</p>
            ) : (
              <>
                <label>Vehicle
                  <select value={idx} disabled={running} onChange={(e) => pick(+e.target.value)}>
                    {sc.vehicles.map((x, i) => <option key={x.run_id} value={i}>{x.plate} · {x.type} · {x.ticks.length} ticks</option>)}
                  </select>
                </label>
                <label>Run ID (create runs below, start one on /vehicle, or use the scenario's)
                  <input value={runId} disabled={running} onChange={(e) => setRunId(e.target.value)} />
                </label>
              </>
            )}
            <div className="row">
              {[1, 5, 20].map((s) => (
                <button key={s} className={speed === s ? "primary" : ""} disabled={running} onClick={() => setSpeed(s)}>{s}x</button>
              ))}
            </div>
            {running ? <button className="danger" onClick={halt}>Stop</button> : <button className="primary" onClick={start}>Start</button>}
            {seen.length === 0 && <p className="muted">{running ? "Sending first tick…" : "Idle."}</p>}
            {seen.map((x) => {
              const p = progs[x.plate];
              return <p key={x.plate} className="muted">{x.plate} · tick {p.i}/{p.n} · t={p.t}s · last response: {p.status}{p.i === p.n ? " · done" : ""}</p>;
            })}
            {seen.some((x) => progs[x.plate].status !== 200) && <p className="muted">501 is expected until /location is implemented; the feed keeps going.</p>}
            <h2>Runs for this scenario</h2>
            <p className="muted">/location needs real runs. This issues one incident and one run per vehicle (confirming the ambulance tiers) and remembers the ids in this browser.</p>
            <button disabled={running || creating} onClick={createRuns}>{creating ? "Creating…" : "Create runs for this scenario"}</button>
            {createErr && <p className="card bad">Could not create runs — {createErr}</p>}
            {sc.vehicles.filter((x) => map[x.plate]).map((x) => <p key={x.plate} className="muted">{x.plate} → {map[x.plate]}</p>)}
          </section>
        </div>
      </div>
    </>
  );
}

// ---------------- Replay: with-vs-without, purely client side from the scenario file ----------------
const Strip = ({ items }) => (
  <div className="jstrip">
    {items.map((i) => (
      <div key={i.id} className={`jchip ${i.tone}`}>
        <svg viewBox="0 0 40 40" aria-hidden="true">
          <circle cx="20" cy="20" r="8" className="jdot" />
          {i.ring != null && <circle cx="20" cy="20" r={8 + 11 * i.ring} className="jring" />}
        </svg>
        <b>{i.id}</b><span>{i.label}</span>
      </div>
    ))}
  </div>
);

function Replay({ scn, setScn }) {
  const sc = scenarios[scn];
  const corridor = corridors[sc.corridor];
  const sim = useMemo(() => simulate(sc, corridor), [sc, corridor]);
  const [T, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(5);
  const end = Math.ceil(sim.end_s);
  useEffect(() => { setT(0); setPlaying(false); }, [sim]);
  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    const id = setInterval(() => {
      const n = performance.now();
      setT((t) => Math.min(end, t + ((n - last) / 1000) * speed));
      last = n;
    }, 100);
    return () => clearInterval(id);
  }, [playing, speed, end]);
  useEffect(() => { if (playing && T >= end) setPlaying(false); }, [T, playing, end]);

  const key = (j) => `${corridor.id}_${j}`;
  const lane = (holds) => sim.vehicles.map((x) => ({ x, s: at(x, x[holds], T) }));
  const today = lane("holdsWithout"), withC = lane("holdsWith");
  const markers = (l) => l.filter(({ s }) => s.started).map(({ x, s }) => ({ id: x.id, type: x.type, lat: s.lat, lng: s.lng }));
  const spans = spansAt(sc.recorded_spans, T);

  // Today: junctions stay grey, the dot shows the seconds left on the current wait
  const phToday = {}, ringToday = {}, waited = {};
  for (const { x, s } of today) {
    for (const h of x.holdsWithout) waited[h.junction] = (waited[h.junction] ?? 0) + Math.min(Math.max(T - h.at, 0), h.d);
    if (s.hold) {
      phToday[key(s.hold.junction)] = { approach: String(Math.ceil(s.hold.at + s.hold.d - T)), until: 0 };
      ringToday[s.hold.junction] = Math.max(ringToday[s.hold.junction] ?? 0, (T - s.hold.at) / s.hold.d);
    }
  }
  // With corridor: a junction is green from the PREPARE alert until the vehicle clears it
  const phWith = {}, alertWith = {}, passed = new Set();
  for (const { x, s } of withC) {
    if (!s.started) continue;
    for (const p of x.passes) {
      const eta = p.t - s.local, st = stage(eta, p.clear_s);
      if (st && (eta > 0 || s.hold?.junction === p.junction)) {
        phWith[key(p.junction)] = { approach: p.approach ?? st, until: Date.now() + 15000 };
        alertWith[p.junction] = st;
      } else if (eta <= 0) passed.add(p.junction);
    }
  }
  const seq = sim.sequencing.filter((q) => T >= q.at - 45);

  const left = corridor.junctions.map((j) => {
    const w = waited[j.id] ?? 0;
    return { id: j.id, ring: ringToday[j.id] ?? null, tone: ringToday[j.id] != null ? "bad" : "", label: w > 0 ? `${Math.round(w)} s` : "—" };
  });
  const right = corridor.junctions.map((j) => ({
    id: j.id, ring: null, tone: alertWith[j.id] ? "good" : "",
    label: alertWith[j.id] ?? (passed.has(j.id) ? "passed" : "—"),
  }));
  const saved = savedAt(sim.vehicles, T);

  return (
    <div className="replay">
      <section className="card saved">
        <div className="muted">Minutes saved</div>
        <div className="bignum" aria-live="off">{(saved / 60).toFixed(1)}<small> min</small></div>
        <div className="muted">of {(sim.saved_s / 60).toFixed(1)} min over {sim.vehicles.length} vehicles · simulated estimate on recorded traffic</div>
      </section>
      <section className="card controls">
        <div className="row">
          <button className="primary" onClick={() => { if (T >= end) setT(0); setPlaying(!playing); }}>{playing ? "Pause" : T >= end ? "Replay" : "Play"}</button>
          {[1, 5, 20].map((s) => <button key={s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>{s}x</button>)}
        </div>
        <input type="range" min="0" max={end} step="1" value={Math.round(T)} onChange={(e) => setT(+e.target.value)} aria-label="Replay time" />
        <div className="muted">t = {mmss(T)} / {mmss(end)}</div>
        <ScenarioSelect value={scn} onChange={setScn} />
      </section>
      <div className="rgrid">
        <section className="rpane">
          <h2>Today <span className="muted">stops at every red</span></h2>
          <div className="simmap rmap"><CorridorMap corridor={corridor} vehicles={markers(today)} spans={spans} phases={phToday} /></div>
          <Strip items={left} />
        </section>
        <section className="rpane">
          <h2>With corridor <span className="muted">green ahead, no stops</span></h2>
          <div className="simmap rmap"><CorridorMap corridor={corridor} vehicles={markers(withC)} spans={spans} phases={phWith} /></div>
          <Strip items={right} />
          {seq.map((q) => <p key={q.junction + q.text} className="seq"><b>{q.junction}</b> · {q.text}</p>)}
        </section>
      </div>
      <section className="card">
        <h2>Per vehicle</h2>
        {sim.vehicles.map((x) => (
          <div key={x.id} className="run">
            <div><b>{x.plate}</b> <span className="muted">{x.type}</span><span className={`tp t-${x.tier}`}>{dash(x.tier)}</span></div>
            <dl>
              <dt>Today</dt><dd>{mmss(x.without_s)}</dd>
              <dt>With</dt><dd>{mmss(x.with_s)}</dd>
              <dt>Saved</dt><dd>{mmss(x.saved_s)}</dd>
              <dt>So far</dt><dd>{mmss(Math.max(0, at(x, x.holdsWithout, T).delay - at(x, x.holdsWith, T).delay))}</dd>
            </dl>
            <div className="muted">{x.stops.length ? `Stops today: ${x.stops.map((s) => `${s.junction} ${Math.round(s.wait_s)} s`).join(" · ")}` : "No stops today."}</div>
          </div>
        ))}
        <p className="muted">{sc.baseline_cycle?.note}</p>
      </section>
    </div>
  );
}

export default function Sim() {
  const q = new URLSearchParams(location.search);
  const [mode, setMode] = useState(q.get("mode") === "replay" ? "replay" : "live");
  const [scn, setScn] = useState(scenarios[q.get("scenario")] ? q.get("scenario") : "blr-two-vehicles");
  return (
    <div className="sim">
      <div className="row modebar">
        {["live", "replay"].map((m) => (
          <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>{m === "live" ? "Live" : "Replay"}</button>
        ))}
      </div>
      {mode === "live" ? <Live scn={scn} setScn={setScn} /> : <Replay scn={scn} setScn={setScn} />}
    </div>
  );
}
