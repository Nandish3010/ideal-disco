import { useEffect, useState } from "react";
import { collection, onSnapshot } from "firebase/firestore";
import { db } from "../firebase.js";
import { corridors } from "../data.js";
import { LIVE, useActiveRuns, useJunctions } from "../live.js";
import CorridorMap from "../map.jsx";
import { Rationale, TraceCard } from "../trace.jsx";
import { ErrCard, Offline, StateBadge, useListen, useNow } from "../ui.jsx";
import "../control.css";

const ESCALATE_S = 20;
const RECENT_S = 600; // the banner shows escalations from the last 10 minutes; older unacked alerts are collapsed
const dur = (s) =>
  s < 120 ? `${s} s` : s < 7200 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`;
const ICON = { ambulance: "🚑", fire: "🚒", police: "🚓" };
const ms = (v) => (v?.toMillis ? v.toMillis() : v ? new Date(v).getTime() : 0);
const clock = (v) => new Date(ms(v)).toLocaleTimeString([], { hour12: false });
const dash = (v, f = (x) => x) => (v == null || v === "" ? "—" : f(v));
const tierOf = (r) => r.confirmed_tier ?? r.acuity_tier;
const ago = (v, now) => (v ? `${Math.max(0, Math.round((now - ms(v)) / 60000))} min ago` : "—");

// Whole (small) collection, optionally keyed by doc id prefix -> {data: rows, loading, error, retry}. ponytail: no query, filter client-side.
function useCol(name, prefix = "") {
  const s = useListen(
    (ok, bad) =>
      onSnapshot(
        collection(db, name),
        (q) =>
          ok(q.docs.filter((d) => d.id.startsWith(prefix)).map((d) => ({ id: d.id, ...d.data() }))),
        (e) => {
          console.warn(`${name} listener:`, e.message);
          bad(e);
        },
      ),
    [name, prefix],
  );
  return { ...s, data: s.data ?? [] };
}

// Every alert of every live run (runs/{id}/alerts, no index). useAlerts in live.js only returns the newest 5,
// which would hide an unacked alert behind newer ones; escalations need all of them.
function useRunAlerts(runIds) {
  const [per, setPer] = useState({});
  const [error, setError] = useState(null);
  const [n, setN] = useState(0);
  const key = runIds.join(",");
  useEffect(() => {
    setPer({});
    setError(null);
    const offs = runIds.map((id) =>
      onSnapshot(
        collection(db, `runs/${id}/alerts`),
        (q) =>
          setPer((p) => ({
            ...p,
            [id]: q.docs.map((d) => ({ id: d.id, run_id: id, ...d.data() })),
          })),
        (e) => {
          console.warn("alerts listener:", id, e.message);
          setError(e.message);
        },
      ),
    );
    return () => offs.forEach((f) => f());
  }, [key, n]); // eslint-disable-line react-hooks/exhaustive-deps -- key is runIds.join()
  return {
    rows: runIds.flatMap((id) => per[id] ?? []).sort((a, b) => ms(b.created_at) - ms(a.created_at)),
    loading: !error && runIds.some((id) => !per[id]),
    error,
    retry: () => setN((x) => x + 1),
  };
}

const Badge = ({ cls, children }) => <span className={`cb ${cls}`}>{children}</span>;

export default function Control() {
  const [cid, setCid] = useState(() => {
    const c = new URLSearchParams(location.search).get("corridor");
    return corridors[c] ? c : "blr";
  });
  const corridor = corridors[cid];
  const pick = (c) => {
    setCid(c);
    history.replaceState(null, "", `?corridor=${c}`);
  };
  const now = useNow();
  const jq = useJunctions(cid),
    junctions = jq.data;
  const rq = useActiveRuns(cid),
    runs = rq.data;
  // escalations come only from runs still moving (arrived runs are history)
  const aq = useRunAlerts(
      runs
        .filter((r) => LIVE.includes(r.state))
        .map((r) => r.id)
        .sort(),
    ),
    alerts = aq.rows;
  const dq = useCol("duty", `${cid}_`);
  const duty = Object.fromEntries(dq.data.map((d) => [d.id, d]));
  const pq = useCol("reports");
  const reports = pq.data
    .filter((r) => !r.corridor || r.corridor === cid)
    .sort((a, b) => ms(b.generated_at ?? b.created_at) - ms(a.generated_at ?? a.created_at));
  const [sel, setSel] = useState(null);

  const jname = (id) =>
    corridor.junctions.find((j) => `${cid}_${j.id}` === id || j.id === id)?.name ?? id;
  const runOf = (id) => runs.find((r) => r.id === id);
  const age = (a) => (a.created_at ? Math.round((now - ms(a.created_at)) / 1000) : 0);
  const late = (a) => !a.acked_at && (a.escalated || age(a) > ESCALATE_S);
  const unacked = alerts.filter(late);
  const esc = unacked.filter((a) => age(a) <= RECENT_S),
    older = unacked.filter((a) => age(a) > RECENT_S);
  const stageOf = (r) => r.stage ?? alerts.find((a) => a.run_id === r.id)?.stage;

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
  const s = runOf(sel);

  return (
    <div className="control">
      <Offline />
      <ErrCard what="active runs" error={rq.error} retry={rq.retry} />
      <ErrCard what="alerts" error={aq.error} retry={aq.retry} />
      <ErrCard what="junction state" error={jq.error} retry={jq.retry} />
      {esc.length > 0 && (
        <section className="escs" role="alert">
          <b>
            {esc.length} ESCALATED, no ACK in {ESCALATE_S} s
          </b>
          {esc.map((a) => {
            const r = runOf(a.run_id);
            return (
              <div key={`${a.run_id}/${a.id}`} className="esc">
                <span>
                  <b>
                    {a.junction_id?.split("_").pop().toUpperCase()} {jname(a.junction_id)}
                  </b>
                  : {dash(a.stage)} alert unacked {dur(age(a))}
                  {r ? ` · ${r.vehicle_type} ${dash(tierOf(r), (t) => t.toUpperCase())}` : ""}
                </span>
                <button title="Placeholder, does nothing yet" onClick={() => {}}>
                  Call junction (placeholder)
                </button>
              </div>
            );
          })}
        </section>
      )}
      {older.length > 0 && (
        <details className="older">
          <summary>Older unacked alerts ({older.length})</summary>
          {older.map((a) => (
            <div key={`${a.run_id}/${a.id}`} className="esc muted">
              <b>
                {a.junction_id?.split("_").pop().toUpperCase()} {jname(a.junction_id)}
              </b>
              : {dash(a.stage)} · unacked {dur(age(a))}
            </div>
          ))}
        </details>
      )}
      <div className="cgrid">
        <div className="cmapbox">
          <CorridorMap
            corridor={corridor}
            junctions={junctions}
            vehicles={vehicles}
            selected={sel}
          />
        </div>
        <div className="cpanel">
          <section className="card">
            <label>
              Corridor
              <select value={cid} onChange={(e) => pick(e.target.value)}>
                {Object.values(corridors).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.id} · {c.name}
                  </option>
                ))}
              </select>
            </label>
            <h2>Active runs ({runs.length})</h2>
            {rq.loading ? (
              <p className="muted">Loading…</p>
            ) : rq.error ? null : runs.length === 0 ? (
              <p className="muted">No vehicles on the corridor right now</p>
            ) : (
              <div className="tscroll">
                <table className="runs">
                  <thead>
                    <tr>
                      <th></th>
                      <th>Plate</th>
                      <th>Tier</th>
                      <th>State</th>
                      <th>Next</th>
                      <th>ETA</th>
                      <th>Stage</th>
                      <th>Incident</th>
                      <th>Started</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((r) => (
                      <tr
                        key={r.id}
                        className={`${r.id === sel ? "sel " : ""}st-${r.state}`}
                        onClick={() => setSel(r.id === sel ? null : r.id)}
                      >
                        <td>{ICON[r.vehicle_type] ?? "?"}</td>
                        <td>
                          <b>{r.vehicle_plate ?? r.id}</b>
                        </td>
                        <td>
                          {tierOf(r) ? <Badge cls={`t-${tierOf(r)}`}>{tierOf(r)}</Badge> : "—"}
                        </td>
                        <td>
                          <StateBadge run={r} now={now} />
                        </td>
                        <td>{dash(r.next_junction_id ?? r.next_junction, jname)}</td>
                        <td>{dash(r.eta_s, (x) => `${x} s`)}</td>
                        <td>{dash(stageOf(r))}</td>
                        <td>{dash(r.incident_id)}</td>
                        <td>{ago(r.started_at, now)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {s && (
              <dl className="detail">
                <dt>Run</dt>
                <dd>{s.id}</dd>
                <dt>Destination</dt>
                <dd>{dash(s.destination?.name)}</dd>
                <dt>Hospital ETA</dt>
                <dd>{dash(s.eta_hospital_s, (x) => `${x} s`)}</dd>
                <dt>Source</dt>
                <dd>{dash(s.source)}</dd>
                <dt>Last tick</dt>
                <dd>{dash(s.last_tick_at, (x) => clock(x))}</dd>
                <dt>Patient on board</dt>
                <dd>{s.patient_on_board ? "yes" : "no"}</dd>
              </dl>
            )}
            {s && (
              <TraceCard
                routing={s.routing}
                pending={!!s.confirmed_tier && s.vehicle_type === "ambulance"}
              />
            )}
          </section>

          <section className="card">
            <h2>Junction board</h2>
            <ErrCard what="cop duty roster" error={dq.error} retry={dq.retry} />
            <div className="jboard">
              {corridor.junctions.map((j) => {
                const key = `${cid}_${j.id}`;
                const ph = junctions[key]?.phase;
                const green = ph && ms(ph.until) > now;
                const mine = alerts.filter((a) => a.junction_id === key || a.junction_id === j.id);
                const a = mine[0];
                const hot = mine.some((x) => late(x) && age(x) <= RECENT_S);
                const d = duty[key];
                return (
                  <div key={j.id} className={`jcard${hot ? " hot" : ""}`}>
                    <div className="jh">
                      <b>
                        {j.id.toUpperCase()} {j.name}
                      </b>
                      {hot && <Badge cls="esc-b">ESCALATED</Badge>}
                    </div>
                    <div className={green ? "ph on" : "ph"}>
                      {green ? `GREEN for ${ph.approach} until ${clock(ph.until)}` : "Normal cycle"}
                    </div>
                    {green && <Rationale phase={ph} runs={runs} />}
                    <div className="muted">
                      {d
                        ? `Cop: ${d.name ?? d.cop ?? d.cop_name ?? "on duty"}`
                        : "no cop registered"}
                    </div>
                    {a ? (
                      <div className="ja">
                        <Badge cls={`s-${a.stage}`}>{dash(a.stage)}</Badge>{" "}
                        {a.acked_at ? (
                          <>ACKed · {((ms(a.acked_at) - ms(a.created_at)) / 1000).toFixed(1)} s</>
                        ) : (
                          <span className={late(a) && age(a) <= RECENT_S ? "bad" : ""}>
                            unacked {dur(age(a))}
                          </span>
                        )}
                      </div>
                    ) : (
                      <div className="muted">no alerts</div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>

          <section className="card">
            <h2>Report cards</h2>
            <ErrCard what="report cards" error={pq.error} retry={pq.retry} />
            {pq.loading ? (
              <p className="muted">Loading…</p>
            ) : pq.error ? null : reports.length === 0 ? (
              <p className="muted">No completed runs yet.</p>
            ) : (
              reports.map((r) => (
                <div key={r.id} className="rep">
                  <b>{r.id}</b>
                  <span>{dash(r.minutes_saved, (m) => `${m} min saved`)}</span>
                  <span className="muted">
                    {dash(r.baseline_s)} s baseline → {dash(r.actual_s)} s actual ·{" "}
                    {dash(r.junctions_cleared)} junctions
                    {r.ack_latency_s?.length ? ` · ACK ${r.ack_latency_s.join(", ")} s` : ""}
                  </span>
                </div>
              ))
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
