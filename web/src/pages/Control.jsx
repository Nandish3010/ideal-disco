import { useEffect, useState } from "react";
import { collection, onSnapshot } from "firebase/firestore";
import { db } from "../firebase.js";
import { corridors } from "../data.js";
import { LIVE, useActiveRuns, useJunctions } from "../live.js";
import CorridorMap from "../map.jsx";
import { Rationale, TraceCard } from "../trace.jsx";
import { AfterAction } from "./Hospital.jsx";
import { RunLabel } from "../samples.jsx";
import { withMethod } from "../pick.js";
import { mmss } from "../format.js";
import { presence } from "../story.js";
import { ErrCard, Offline, StateBadge, useListen, useNow } from "../ui.jsx";
import { t } from "../i18n/index.js";
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
const ago = (v, now) =>
  v ? t("control.min_ago", { n: Math.max(0, Math.round((now - ms(v)) / 60000)) }) : "—";

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
  const aq = useRunAlerts(runs.map((r) => r.id).sort()),
    liveIds = runs.filter((r) => LIVE.includes(r.state)).map((r) => r.id),
    alerts = aq.rows.filter((a) => liveIds.includes(a.run_id));
  const dq = useCol("duty", `${cid}_`);
  const duty = Object.fromEntries(dq.data.map((d) => [d.id, d]));
  const pq = useCol("reports");
  const reports = withMethod(pq.data)
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
      <ErrCard what={t("what.active_runs")} error={rq.error} retry={rq.retry} />
      <ErrCard what={t("what.alerts")} error={aq.error} retry={aq.retry} />
      <ErrCard what={t("what.junctions")} error={jq.error} retry={jq.retry} />
      {esc.length > 0 && (
        <section className="escs" role="alert">
          <b>{t("control.escalated", { n: esc.length, s: ESCALATE_S })}</b>
          {esc.map((a) => {
            const r = runOf(a.run_id);
            return (
              <div key={`${a.run_id}/${a.id}`} className="esc">
                <span>
                  <b>
                    {a.junction_id?.split("_").pop().toUpperCase()} {jname(a.junction_id)}
                  </b>
                  : {t("control.alert_unacked", { stage: dash(a.stage), age: dur(age(a)) })}
                  {r ? ` · ${r.vehicle_type} ${dash(tierOf(r), (t) => t.toUpperCase())}` : ""}
                </span>
                <Badge cls="esc-b">{t("control.escalate")}</Badge>
              </div>
            );
          })}
        </section>
      )}
      {older.length > 0 && (
        <details className="older">
          <summary>{t("control.older", { n: older.length })}</summary>
          {older.map((a) => (
            <div key={`${a.run_id}/${a.id}`} className="esc muted">
              <b>
                {a.junction_id?.split("_").pop().toUpperCase()} {jname(a.junction_id)}
              </b>
              : {dash(a.stage)} · {t("control.unacked", { age: dur(age(a)) })}
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
              {t("cop.corridor")}
              <select value={cid} onChange={(e) => pick(e.target.value)}>
                {Object.values(corridors).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.id} · {c.name}
                  </option>
                ))}
              </select>
            </label>
            <h2>{t("control.active", { n: runs.length })}</h2>
            {rq.loading ? (
              <p className="muted">{t("common.loading")}</p>
            ) : rq.error ? null : runs.length === 0 ? (
              <p className="muted">{t("control.no_vehicles")}</p>
            ) : (
              <div className="tscroll">
                <table className="runs">
                  <thead>
                    <tr>
                      <th>
                        <span className="sr-only">{t("control.th_type")}</span>
                      </th>
                      <th>{t("control.th_plate")}</th>
                      <th>{t("control.th_tier")}</th>
                      <th>{t("control.th_state")}</th>
                      <th>{t("control.th_next")}</th>
                      <th>ETA</th>
                      <th>{t("control.th_stage")}</th>
                      <th>{t("control.th_incident")}</th>
                      <th>{t("control.th_started")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((r) => (
                      <tr
                        key={r.id}
                        className={`${r.id === sel ? "sel " : ""}st-${r.state}`}
                        tabIndex={0}
                        aria-selected={r.id === sel}
                        onClick={() => setSel(r.id === sel ? null : r.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setSel(r.id === sel ? null : r.id);
                          }
                        }}
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
                <dt>{t("control.d_run")}</dt>
                <dd>{s.id}</dd>
                <dt>{t("control.d_dest")}</dt>
                <dd>{dash(s.destination?.name)}</dd>
                <dt>{t("control.d_eta")}</dt>
                <dd>{dash(s.eta_hospital_s, (x) => `${x} s`)}</dd>
                <dt>{t("control.d_source")}</dt>
                <dd>{dash(s.source)}</dd>
                <dt>{t("control.d_tick")}</dt>
                <dd>{dash(s.last_tick_at, (x) => clock(x))}</dd>
                <dt>{t("control.d_patient")}</dt>
                <dd>{s.patient_on_board ? t("common.yes") : t("common.no")}</dd>
              </dl>
            )}
            {s && ["ended", "arrived"].includes(s.state) && <AfterAction runId={s.id} />}
            {s && (
              <TraceCard
                routing={s.routing}
                pending={!!s.confirmed_tier && s.vehicle_type === "ambulance"}
              />
            )}
          </section>

          <section className="card">
            <h2>{t("control.board")}</h2>
            <ErrCard what={t("what.duty")} error={dq.error} retry={dq.retry} />
            <div className="jboard">
              {corridor.junctions.map((j) => {
                const key = `${cid}_${j.id}`;
                const ph = junctions[key]?.phase;
                const green = ph && ms(ph.until) > now;
                const mine = alerts.filter((a) => a.junction_id === key || a.junction_id === j.id);
                const a = mine[0];
                const hot = mine.some((x) => late(x) && age(x) <= RECENT_S);
                const pres = presence(
                  duty[key],
                  aq.rows.filter((x) => x.junction_id === key || x.junction_id === j.id),
                  now,
                );
                return (
                  <div key={j.id} className={`jcard${hot ? " hot" : ""}`}>
                    <div className="jh">
                      <b>
                        {j.id.toUpperCase()} {j.name}
                      </b>
                      {hot && <Badge cls="esc-b">{t("cop.escalated")}</Badge>}
                    </div>
                    <div className={green ? "ph on" : "ph"}>
                      {green
                        ? t("control.green", { approach: ph.approach, until: clock(ph.until) })
                        : t("control.normal")}
                    </div>
                    {green && <Rationale phase={ph} runs={runs} />}
                    <div className={pres.on ? "" : "muted"}>{pres.text}</div>
                    {a ? (
                      <div className="ja">
                        <Badge cls={`s-${a.stage}`}>{dash(a.stage)}</Badge>{" "}
                        {a.acked_at ? (
                          <>
                            {t("control.acked", {
                              s: ((ms(a.acked_at) - ms(a.created_at)) / 1000).toFixed(1),
                            })}
                          </>
                        ) : (
                          <span className={late(a) && age(a) <= RECENT_S ? "bad" : ""}>
                            {t("control.unacked", { age: dur(age(a)) })}
                          </span>
                        )}
                      </div>
                    ) : (
                      <div className="muted">{t("control.no_alerts")}</div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>

          <section className="card">
            <h2>{t("control.reports")}</h2>
            <ErrCard what={t("what.reports")} error={pq.error} retry={pq.retry} />
            {pq.loading ? (
              <p className="muted">{t("common.loading")}</p>
            ) : pq.error ? null : reports.length === 0 ? (
              <p className="muted">{t("control.no_reports")}</p>
            ) : (
              reports.map((r) => (
                <div key={r.id} className="rep">
                  <RunLabel id={r.id} tier={r.confirmed_tier} type={r.vehicle_type} />
                  <span>{dash(r.minutes_saved, (m) => t("control.saved", { m }))}</span>
                  <span className="muted">
                    {t("control.baseline_actual", {
                      b: dash(r.baseline_s, mmss),
                      a: dash(r.actual_s, mmss),
                    })}{" "}
                    ·{" "}
                    {dash(r.junctions_cleared, (n) =>
                      t(n === 1 ? "control.junction_1" : "control.junction_n", { n }),
                    )}
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
