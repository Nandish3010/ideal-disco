import { useEffect, useMemo, useRef, useState } from "react";
import { corridors, scenario } from "../data.js";
import blrTwoVehicles from "../../../data/scenarios/blr-two-vehicles.json";
import { startFeed, startFeedAll, startRun } from "../feeder.js";
import { useActiveRuns, useAlerts, useJunctions } from "../live.js";
import CorridorMap, { HAS_MAPS_KEY } from "../map.jsx";
import { Rationale } from "../trace.jsx";
import { ErrCard, Offline, StateBadge, useNow } from "../ui.jsx";
import { mmss, tierLabel, vehicleLabel } from "../format.js";
import { at, lead, savedAt, savedRange, simulate, spansAt, stage } from "../replay.js";
import "../sim.css";

const scenarios = { example: scenario, "blr-two-vehicles": blrTwoVehicles };
const dash = (v, f = (x) => x) => (v == null || v === "" ? "—" : f(v));
const tierOf = (r) => r.confirmed_tier ?? r.acuity_tier;

// scenario vehicle -> run id, kept per scenario in localStorage (the feeder writes it when it starts a run)
const storeKey = (scn) => `sim.runs.${scn}`;
const loadRuns = (scn) => {
  try {
    return JSON.parse(localStorage.getItem(storeKey(scn))) ?? {};
  } catch {
    return {};
  }
};
const saveRuns = (scn, m) => {
  try {
    localStorage.setItem(storeKey(scn), JSON.stringify(m));
  } catch {
    /* private mode */
  }
};

function Alerts({ rows, mode, loading, error, retry }) {
  return (
    <div
      className="alerts"
      title={mode === "per-run" ? "per-run reads (collectionGroup index missing)" : undefined}
    >
      <ErrCard what="alerts" error={error} retry={retry} />
      {loading && <span className="muted">Loading…</span>}
      {!loading && !error && rows.length === 0 && <span className="muted">No alerts yet.</span>}
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
    <label>
      Scenario
      <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {Object.keys(scenarios).map((k) => (
          <option key={k} value={k}>
            Scenario: {k}
          </option>
        ))}
      </select>
    </label>
  );
}

// ---------------- Live: Firestore twin + GPS feeder ----------------
function Live({ scn, setScn }) {
  const [cid, setCid] = useState(() => {
    const c = new URLSearchParams(location.search).get("corridor");
    return corridors[c] ? c : "blr";
  });
  const corridor = corridors[cid];
  const now = useNow();
  const jq = useJunctions(cid),
    junctions = jq.data;
  const rq = useActiveRuns(cid),
    runs = rq.data;
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
  const [create, setCreate] = useState(true); // start each run (POST /runs) right before its vehicle's first tick
  const [warns, setWarns] = useState({}); // {plate: warning from starting the run}
  const stop = useRef(null);
  useEffect(() => () => stop.current?.(), []);

  const pickScn = (k) => {
    setScn(k);
    setIdx(0);
    setMap(loadRuns(k));
    setRunId(loadRuns(k)[scenarios[k].vehicles[0].plate] ?? scenarios[k].vehicles[0].run_id);
    setWarns({});
  };
  const pick = (i) => {
    setIdx(i);
    setRunId(map[sc.vehicles[i].plate] ?? sc.vehicles[i].run_id);
  };

  // a run was just started by the feeder: remember it (it replaces any older run id for that plate)
  const gotRun = (plate, id, warn) => {
    setMap((m) => {
      const n = { ...m, [plate]: id };
      saveRuns(scn, n);
      return n;
    });
    setFed((f) => ({ ...f, [plate]: id }));
    if (plate === v.plate) setRunId(id);
    setWarns((w) => ({ ...w, [plate]: warn }));
  };
  const begin = create
    ? (x) =>
        startRun({
          vehicle: x,
          scenarioName: scn,
          corridor: sc.corridor,
          destination: corridors[sc.corridor]?.hospital,
        })
    : undefined;

  const start = () => {
    setRunning(true);
    setProgs({});
    setWarns({});
    const onTick = (p) => setProgs((s) => ({ ...s, [p.plate ?? v.plate]: p }));
    const onDone = () => setRunning(false);
    if (all) {
      const ids = Object.fromEntries(sc.vehicles.map((x) => [x.plate, map[x.plate] ?? x.run_id]));
      setFed(create ? {} : ids);
      stop.current = startFeedAll({
        scenario: sc,
        runIds: ids,
        begin,
        speed,
        onTick,
        onDone,
        onRun: gotRun,
      });
    } else {
      setFed(create ? {} : { [v.plate]: runId });
      stop.current = startFeed({
        vehicle: v,
        runId,
        begin,
        speed,
        onTick,
        onDone,
        onRun: (id, w) => gotRun(v.plate, id, w),
      });
    }
  };
  const halt = () => {
    stop.current?.();
    setRunning(false);
  };

  // vehicles at their last tick; the feeder's own position fills in until the backend writes ticks[]
  const vehicles = runs
    .map((r) => {
      const k = r.ticks?.at(-1);
      return {
        id: r.id,
        type: r.vehicle_type,
        lat: k?.lat ?? r.lat,
        lng: k?.lng ?? r.lng,
        stale: r.state === "stale",
      };
    })
    .filter((x) => Number.isFinite(x.lat));
  for (const x of sc.vehicles) {
    const p = progs[x.plate];
    if (p?.i > 0 && fed[x.plate] && !vehicles.some((y) => y.id === fed[x.plate])) {
      const k = x.ticks[p.i - 1];
      vehicles.push({ id: fed[x.plate], type: x.type, lat: k.lat, lng: k.lng });
    }
  }
  // scenario clock for the recorded spans: latest tick time, plus the start offset when everyone runs together
  const tNow = Math.max(
    0,
    ...sc.vehicles.map((x) =>
      progs[x.plate] ? (all ? (x.start_offset_s ?? 0) : 0) + progs[x.plate].t : 0,
    ),
  );
  const spans = running && sc.corridor === cid ? spansAt(sc.recorded_spans, tNow) : undefined;
  const stageOf = (r) => r.stage ?? alerts.rows.find((a) => a.run_id === r.id)?.stage;
  const seen = sc.vehicles.filter((x) => progs[x.plate]);
  const ms = (v) => (v?.toMillis ? v.toMillis() : v ? new Date(v).getTime() : 0);
  const seqs = corridor.junctions
    .map((j) => {
      const jd = junctions[`${cid}_${j.id}`];
      return { j, ph: ms(jd?.phase?.until) > now ? jd.phase : null, last: jd?.last_sequence };
    })
    .filter(({ ph, last }) => ph?.sequence?.length >= 2 || last?.sequence?.length >= 2);

  return (
    <>
      <ErrCard what="active runs" error={rq.error} retry={rq.retry} />
      <ErrCard what="junction state" error={jq.error} retry={jq.retry} />
      <Alerts {...alerts} />
      <div className="simgrid">
        <div className="simmap">
          <CorridorMap
            corridor={corridor}
            junctions={junctions}
            vehicles={vehicles}
            spans={spans}
          />
        </div>
        <div className="simpanel">
          <section className="card">
            <label>
              Corridor
              <select value={cid} onChange={(e) => pickCorridor(e.target.value)}>
                {Object.values(corridors).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.id} · {c.name}
                  </option>
                ))}
              </select>
            </label>
            <h2>Active runs ({runs.length})</h2>
            {rq.loading && <p className="muted">Loading…</p>}
            {!rq.loading && !rq.error && runs.length === 0 && (
              <p className="muted">No vehicles on the corridor right now</p>
            )}
            {runs.map((r) => (
              <div key={r.id} className="run">
                <div>
                  <b>{r.vehicle_plate ?? r.id}</b>{" "}
                  <span className="muted">{dash(r.vehicle_type)}</span>
                  <span className={`tp t-${tierOf(r)}`}>{dash(tierOf(r), tierLabel)}</span>
                </div>
                <dl>
                  <dt>Next</dt>
                  <dd>{dash(r.next_junction_id)}</dd>
                  <dt>ETA</dt>
                  <dd>{dash(r.eta_s, (s) => `${s} s`)}</dd>
                  <dt>Stage</dt>
                  <dd>{dash(stageOf(r))}</dd>
                  <dt>State</dt>
                  <dd>
                    <StateBadge run={r} now={now} />
                  </dd>
                </dl>
              </div>
            ))}
          </section>
          {seqs.length > 0 && (
            <section className="card">
              <h2>Junction sequencing</h2>
              {seqs.map(({ j, ph, last }) => (
                <div key={j.id}>
                  <b>{j.id.toUpperCase()}</b>
                  <Rationale phase={ph} runs={runs} last={last} />
                </div>
              ))}
            </section>
          )}
          <section className="card">
            <h2>GPS feeder</h2>
            <ScenarioSelect value={scn} disabled={running} onChange={pickScn} />
            {sc.corridor !== cid && (
              <p className="muted">
                This scenario is for {sc.corridor}; select that corridor to see its spans.
              </p>
            )}
            <div className="row">
              <button className={!all ? "on" : ""} disabled={running} onClick={() => setAll(false)}>
                One vehicle
              </button>
              <button className={all ? "on" : ""} disabled={running} onClick={() => setAll(true)}>
                All vehicles
              </button>
            </div>
            {all ? (
              <p className="muted">
                Runs every vehicle, each starting at its offset (
                {sc.vehicles.map((x) => `${x.plate} +${x.start_offset_s ?? 0} s`).join(", ")}).
              </p>
            ) : (
              <>
                <label>
                  Vehicle
                  <select value={idx} disabled={running} onChange={(e) => pick(+e.target.value)}>
                    {sc.vehicles.map((x, i) => (
                      <option key={x.run_id} value={i}>
                        {x.plate} · {x.type} · {x.ticks.length} ticks
                      </option>
                    ))}
                  </select>
                </label>
                {!create && (
                  <label>
                    Run ID (start one on /vehicle, or use the scenario&apos;s)
                    <input
                      value={runId}
                      disabled={running}
                      onChange={(e) => setRunId(e.target.value)}
                    />
                  </label>
                )}
              </>
            )}
            <div className="row">
              {[1, 5, 20].map((s) => (
                <button
                  key={s}
                  className={speed === s ? "primary" : ""}
                  disabled={running}
                  onClick={() => setSpeed(s)}
                >
                  {s}x
                </button>
              ))}
            </div>
            {running ? (
              <button className="danger" onClick={halt}>
                Stop
              </button>
            ) : (
              <button className="primary" onClick={start}>
                Start
              </button>
            )}
            {seen.length === 0 && (
              <p className="muted">{running ? "Sending first tick…" : "Idle."}</p>
            )}
            {seen.map((x) => {
              const p = progs[x.plate];
              return (
                <p key={x.plate} className="muted">
                  {x.plate} · tick {p.i}/{p.n} · t={p.t}s · last response: {p.status}
                  {p.i === p.n ? " · done" : ""}
                </p>
              );
            })}
            <h2>Runs for this scenario</h2>
            <label className="row">
              <input
                type="checkbox"
                checked={create}
                disabled={running}
                onChange={(e) => setCreate(e.target.checked)}
              />
              Create runs: start each run (incident, run, ambulance tier confirm) right before that
              vehicle&apos;s first tick; the critical ambulance also gets an &quot;aspirin 300 mg
              given&quot; log entry so the hospital brief can generate
            </label>
            {sc.vehicles
              .filter((x) => map[x.plate])
              .map((x) => (
                <p key={x.plate} className="muted">
                  {x.plate} → {map[x.plate]}
                </p>
              ))}
            {Object.entries(warns)
              .filter(([, w]) => w)
              .map(([plate, w]) => (
                <p key={plate} className="card bad">
                  {plate}: {w}
                </p>
              ))}
            <p className="muted">
              Reset demo data (ends old runs, clears alerts, audit and duty):{" "}
              <code>python3 scripts/demo_reset.py --apply</code>, see the{" "}
              <a
                href="https://github.com/Nandish3010/ideal-disco#reset-demo-data"
                target="_blank"
                rel="noreferrer"
              >
                README
              </a>
              . Nothing is called from this page.
            </p>
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
        <b>{i.id}</b>
        <span>{i.label}</span>
      </div>
    ))}
  </div>
);

function Replay({ scn, setScn }) {
  const sc = scenarios[scn];
  const corridor = corridors[sc.corridor];
  const sim = useMemo(() => simulate(sc, corridor), [sc, corridor]);
  const range = useMemo(() => savedRange(sc, corridor), [sc, corridor]);
  const [T, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(() => {
    const v = Number(new URLSearchParams(location.search).get("speed")); // ?speed=5|20|50
    return [5, 20, 50].includes(v) ? v : 20;
  });
  const end = Math.ceil(sim.end_s);
  const auto = useRef(new URLSearchParams(location.search).get("autoplay") === "1"); // first load only
  useEffect(() => {
    setT(0);
    setPlaying(auto.current);
    auto.current = false;
  }, [sim]);
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
  useEffect(() => {
    if (playing && T >= end) setPlaying(false);
  }, [T, playing, end]);

  const key = (j) => `${corridor.id}_${j}`;
  const lane = (holds) => sim.vehicles.map((x) => ({ x, s: at(x, x[holds], T) }));
  const today = lane("holdsWithout"),
    withC = lane("holdsWith");
  const markers = (l) =>
    l
      .filter(({ s }) => s.started)
      .map(({ x, s }) => ({ id: x.id, type: x.type, lat: s.lat, lng: s.lng }));
  const spans = spansAt(sc.recorded_spans, T);

  // Today: junctions stay grey, the dot shows the seconds left on the current wait
  const phToday = {},
    ringToday = {},
    waited = {};
  for (const { x, s } of today) {
    for (const h of x.holdsWithout)
      waited[h.junction] = (waited[h.junction] ?? 0) + Math.min(Math.max(T - h.at, 0), h.d);
    if (s.hold) {
      phToday[key(s.hold.junction)] = {
        approach: String(Math.ceil(s.hold.at + s.hold.d - T)),
        until: 0,
      };
      ringToday[s.hold.junction] = Math.max(
        ringToday[s.hold.junction] ?? 0,
        (T - s.hold.at) / s.hold.d,
      );
    }
  }
  // With corridor: a junction is green from the PREPARE alert until the vehicle clears it
  const phWith = {},
    alertWith = {},
    passed = new Set();
  for (const { x, s } of withC) {
    if (!s.started) continue;
    for (const p of x.passes) {
      const eta = p.t - s.local,
        st = stage(eta, p.clear_s);
      if (st && (eta > 0 || s.hold?.junction === p.junction)) {
        phWith[key(p.junction)] = { approach: p.approach ?? st, until: Date.now() + 15000 };
        alertWith[p.junction] = st;
      } else if (eta <= 0) passed.add(p.junction);
    }
  }
  const seq = sim.sequencing.filter((q) => T >= q.at - 45);

  const left = corridor.junctions.map((j) => {
    const w = waited[j.id] ?? 0;
    return {
      id: j.id,
      ring: ringToday[j.id] ?? null,
      tone: ringToday[j.id] != null ? "bad" : "",
      label: w > 0 ? `${Math.round(w)} s` : "—",
    };
  });
  const right = corridor.junctions.map((j) => ({
    id: j.id,
    ring: null,
    tone: alertWith[j.id] ? "good" : "",
    label: alertWith[j.id] ?? (passed.has(j.id) ? "passed" : "—"),
  }));
  const head = lead(sim); // the counter follows the critical ambulance; the all-vehicle total is the secondary line
  const saved = savedAt([head], T);

  return (
    <div className="replay">
      <div className="rtop">
        <section className="card saved">
          <div className="muted">
            Minutes saved, {head.tier === "critical" ? "critical ambulance" : head.plate}
          </div>
          <div className="bignum" role="status" aria-live={playing ? "off" : "polite"}>
            {(saved / 60).toFixed(1)}
            <small> min</small>
          </div>
          <div className="muted">
            of {(head.saved_s / 60).toFixed(1)} min · all {sim.vehicles.length} vehicles together:{" "}
            {(sim.saved_s / 60).toFixed(1)} min (simulated baseline) · queue drains at 1–3 m/s →{" "}
            {range[0].toFixed(1)}–{range[1].toFixed(1)} min · scripted scenario with hand-authored
            traffic spans
          </div>
        </section>
        <section className="card controls">
          <div className="row">
            <button
              className="primary"
              onClick={() => {
                if (T >= end) setT(0);
                setPlaying(!playing);
              }}
            >
              {playing ? "Pause" : T >= end ? "Replay" : "Play"}
            </button>
            {[5, 20, 50].map((s) => (
              <button key={s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>
                {s}x
              </button>
            ))}
            <ScenarioSelect value={scn} onChange={setScn} />
          </div>
          <input
            type="range"
            min="0"
            max={end}
            step="1"
            value={Math.round(T)}
            onChange={(e) => setT(+e.target.value)}
            aria-label="Replay time"
          />
          <div className="muted">
            t = {mmss(T)} / {mmss(end)}
          </div>
        </section>
      </div>
      <div className="rgrid">
        <section className="rpane">
          <h2>
            Today <span className="muted">stops at every red</span>
          </h2>
          <div className="simmap rmap">
            <CorridorMap
              corridor={corridor}
              vehicles={markers(today)}
              spans={spans}
              phases={phToday}
            />
          </div>
          <Strip items={left} />
        </section>
        <section className="rpane">
          <h2>
            With corridor <span className="muted">green ahead, no stops</span>
          </h2>
          <div className="simmap rmap">
            <CorridorMap
              corridor={corridor}
              vehicles={markers(withC)}
              spans={spans}
              phases={phWith}
            />
          </div>
          <Strip items={right} />
          {seq.map((q) => (
            <p key={q.junction + q.text} className="seq">
              <b>{q.junction}</b> · {q.text}
            </p>
          ))}
        </section>
      </div>
      <section className="card">
        <h2>Per vehicle</h2>
        {sim.vehicles.map((x) => (
          <div key={x.id} className="run">
            <div>
              <b>{x.plate}</b> <span className="muted">{vehicleLabel(x.type, x.tier)}</span>
            </div>
            <dl>
              <dt>Today</dt>
              <dd>{mmss(x.without_s)}</dd>
              <dt>With</dt>
              <dd>{mmss(x.with_s)}</dd>
              <dt>Saved</dt>
              <dd>{mmss(x.saved_s)}</dd>
              <dt>So far</dt>
              <dd>
                {mmss(Math.max(0, at(x, x.holdsWithout, T).delay - at(x, x.holdsWith, T).delay))}
              </dd>
            </dl>
            <div className="muted">
              {x.stops.length
                ? `Stops today: ${x.stops.map((s) => `${s.junction} ${Math.round(s.wait_s)} s`).join(" · ")}`
                : "No stops today."}
            </div>
          </div>
        ))}
        <p className="muted">
          Simulated baseline on a scripted scenario, not a field measurement. Per junction passed:
          cycle/4 + queue/2 m/s (the expected remaining red plus the queue draining at 2 m/s).
        </p>
      </section>
    </div>
  );
}

export default function Sim() {
  const q = new URLSearchParams(location.search);
  const [mode, setMode] = useState(q.get("mode") === "live" ? "live" : "replay");
  const [scn, setScn] = useState(
    scenarios[q.get("scenario")] ? q.get("scenario") : "blr-two-vehicles",
  );
  return (
    <div className="sim">
      <Offline />
      <div className="simtop">
        <div className="row modebar">
          {["replay", "live"].map((m) => (
            <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>
              {m === "live" ? "Live" : "Replay"}
            </button>
          ))}
        </div>
        <p className="muted legend">
          Track <i className="sw jam" />
          jam <i className="sw slow" />
          slow · junction <i className="sw go" />
          green = corridor open · A ambulance, F fire, P police ·{" "}
          <span className="cb st-stale">STALE</span>{" "}
          <span className="cb st-off_route">OFF ROUTE</span>{" "}
          <span className="cb st-arrived">ARRIVED</span>
          {!HAS_MAPS_KEY && (
            <>
              <br />
              Map preview (SVG fallback)
            </>
          )}
        </p>
      </div>
      {mode === "live" ? <Live scn={scn} setScn={setScn} /> : <Replay scn={scn} setScn={setScn} />}
    </div>
  );
}
