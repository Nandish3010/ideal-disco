import { useEffect, useMemo, useRef, useState } from "react";
import { collection, doc, getDoc, getDocs, query, where } from "firebase/firestore";
import { db } from "../firebase.js";
import { corridors } from "../data.js";
import CorridorMap from "../map.jsx";
import { TraceCard } from "../trace.jsx";
import { ErrCard, Offline } from "../ui.jsx";
import { copNoteText, mmss, seqLine, traceLine, vehicleLabel } from "../format.js";
import { buildTimeline, chooseRun, mapState, ms } from "../story.js";
import "../story.css";

// "The last run, as it happened": one finished run, every document it left behind, merged into one timeline. Firestore reads only.

const one = async (path) => {
  const s = await getDoc(doc(db, path));
  return s.exists() ? { id: s.id, ...s.data() } : null;
};
const many = async (ref) => (await getDocs(ref)).docs.map((d) => ({ id: d.id, ...d.data() }));

async function load(runId) {
  let run;
  if (runId) run = await one(`runs/${runId}`);
  else {
    const rows = await many(
      query(collection(db, "runs"), where("state", "in", ["arrived", "ended"])),
    );
    const newest = rows.sort((a, b) => ms(b.started_at) - ms(a.started_at)).slice(0, 12);
    run = chooseRun(
      await Promise.all(
        newest.map(async (r) => ({
          run: r,
          alerts: (await getDocs(collection(db, `runs/${r.id}/alerts`))).size,
          brief: !!(await one(`briefs/${r.id}`)),
        })),
      ),
    );
  }
  if (!run) return null;
  const [log, alerts, audit, js, brief, report, aar] = await Promise.all([
    many(collection(db, `runs/${run.id}/log`)),
    many(collection(db, `runs/${run.id}/alerts`)),
    many(query(collection(db, "audit"), where("run_id", "==", run.id))),
    many(collection(db, "junctions")),
    one(`briefs/${run.id}`),
    one(`reports/${run.id}`),
    one(`after_action/${run.id}`),
  ]);
  const junctions = Object.fromEntries(js.map((j) => [j.id, j]));
  // the other vehicles named in a junction sequence, so it reads "Fire engine → +0 s" and not a run id
  const others = [...new Set(audit.flatMap((x) => (x.sequence ?? []).map((s) => s.run_id)))].filter(
    (id) => id && id !== run.id,
  );
  const runs = [run, ...(await Promise.all(others.map((id) => one(`runs/${id}`)))).filter(Boolean)];
  return { run, runs, log, alerts, audit, junctions, brief, report, aar };
}

const clock = (t) => new Date(t).toLocaleTimeString([], { hour12: false });
const ATMIST = [
  ["age", "Age"],
  ["time", "Time"],
  ["mechanism", "Mechanism"],
  ["injuries", "Injuries"],
  ["signs", "Signs"],
  ["treatment", "Treatment"],
];
const LOG_KIND = { voice: "Crew voice note", photo: "Monitor photo", form: "Crew form entry" };

function Item({ it, d, play, playing, jname }) {
  const { run } = d;
  switch (it.kind) {
    case "start":
      return (
        <>
          <h3>Run started</h3>
          <p>
            {vehicleLabel(run.vehicle_type, run.confirmed_tier)} · {run.vehicle_plate ?? run.id}
            {run.incident_id ? ` · incident ${run.incident_id}` : ""}
          </p>
        </>
      );
    case "log": {
      const e = it.e;
      return (
        <>
          <h3>{LOG_KIND[e.kind] ?? "Crew note"}</h3>
          {e.transcript_en && <p className="quote">{e.transcript_en}</p>}
          {e.interventions?.length > 0 && (
            <div className="chips">
              {e.interventions.map((i, k) => (
                <span key={k} className="chip">
                  {[i.name, i.dose].filter(Boolean).join(" ")}
                </span>
              ))}
            </div>
          )}
          {e.photo_url && (
            <a href={e.photo_url} target="_blank" rel="noreferrer">
              <img
                className="thumb"
                src={e.photo_url}
                alt="Monitor photo from the crew"
                loading="lazy"
              />
            </a>
          )}
        </>
      );
    }
    case "route":
      return (
        <>
          <h3>
            Crew confirmed the tier
            {it.tier && <span className={`pill tier-${it.tier}`}>{it.tier}</span>}
          </h3>
          {it.routing ? (
            <>
              <div className="compact">
                <TraceCard routing={it.routing} />
              </div>
              <details className="more">
                <summary>How it decided ({it.routing.trace?.length ?? 0} steps)</summary>
                <ol className="muted">
                  {it.routing.trace?.map((e, i) => (
                    <li key={i}>{traceLine(e)}</li>
                  ))}
                </ol>
              </details>
            </>
          ) : (
            <p className="muted">No hospital routing was recorded.</p>
          )}
        </>
      );
    case "alert": {
      const a = it.a;
      const lang = d.junctions[a.junction_id]?.lang;
      const note = copNoteText(a.cop_note, a.junction_id);
      return (
        <>
          <h3>
            <span className={`stg stg-${a.stage}`}>{a.stage}</span> alert at {jname(a.junction_id)}
          </h3>
          <p className="alert-text" lang={a.text_local ? lang : undefined}>
            {a.text_local || a.text}
          </p>
          {a.text_local && <p className="muted">{a.text}</p>}
          {a.audio_url && (
            <button
              onClick={() => play(a.audio_url)}
              aria-label={`Play the ${a.stage} alert at ${jname(a.junction_id)}`}
            >
              {playing === a.audio_url ? "■ Stop" : "▶ Play"}
            </button>
          )}
          <p className="ack">
            {a.acked_at ? (
              <b className="ok">
                ACK in {(a.ack_latency_s ?? (ms(a.acked_at) - ms(a.created_at)) / 1000).toFixed(1)}{" "}
                s
              </b>
            ) : (
              <b className="bad">no ACK</b>
            )}
            {a.escalated && <b className="bad"> · ESCALATED</b>}
          </p>
          {note && <p className="note">{note}</p>}
        </>
      );
    }
    case "phase":
      return (
        <>
          <h3>
            {jname(it.jid)}: green requested{it.approach ? ` for the ${it.approach} approach` : ""}
          </h3>
          {seqLine(it.sequence, d.runs) && <p>{seqLine(it.sequence, d.runs)}</p>}
          {it.rationale && <p className="muted">{it.rationale}</p>}
        </>
      );
    case "brief": {
      const b = it.brief;
      return (
        <>
          <h3>Handover brief reached the hospital</h3>
          <dl className="atm">
            {ATMIST.map(([k, l]) => (
              <div key={k}>
                <dt>{l}</dt>
                <dd>{b.atmist?.[k] ?? "—"}</dd>
              </div>
            ))}
          </dl>
          {b.summary && <p className="muted">{b.summary}</p>}
        </>
      );
    }
    case "arrival":
      return (
        <>
          <h3>{run.state === "arrived" ? "Arrived" : "Run ended"}</h3>
          <p>{run.destination?.name ?? run.routing?.destination ?? "Destination not recorded"}</p>
        </>
      );
    case "report": {
      const r = it.report;
      return (
        <>
          <h3>Report card</h3>
          <p>
            <b className="big">{r.minutes_saved ?? "—"} min saved</b>
            {" · "}
            {r.junctions_cleared ?? 0} {r.junctions_cleared === 1 ? "junction" : "junctions"}{" "}
            cleared
          </p>
          <p className="muted">
            {r.baseline_s != null && r.actual_s != null
              ? `${mmss(r.baseline_s)} baseline → ${mmss(r.actual_s)} actual · `
              : ""}
            simulated estimate, not a measurement
          </p>
        </>
      );
    }
    case "aar":
      return (
        <>
          <h3>After-action summary</h3>
          <p>{it.aar.summary}</p>
          {it.aar.issues?.length > 0 && (
            <ul>
              {it.aar.issues.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          )}
        </>
      );
    default:
      return null;
  }
}

function Timeline({ d }) {
  const { run } = d;
  const corridor = corridors[run.corridor] ?? corridors.blr;
  const items = useMemo(() => buildTimeline(d), [d]);
  const [active, setActive] = useState(items[0].id);
  const [playing, setPlaying] = useState(null);
  const [blocked, setBlocked] = useState(false);
  const audio = useRef(null);
  const root = useRef(null);
  const t0 = items[0].t;
  const jname = (id) => {
    const j = corridor.junctions.find((x) => `${corridor.id}_${x.id}` === id || x.id === id);
    return j ? `${j.id.toUpperCase()} ${j.name}` : id;
  };

  // the item crossing a line under the sticky map is the current one
  useEffect(() => {
    if (!("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver(
      (es) => {
        const hit = es.filter((e) => e.isIntersecting).pop();
        if (hit) setActive(hit.target.dataset.id);
      },
      { rootMargin: "-45% 0px -50% 0px" },
    );
    root.current.querySelectorAll("li[data-id]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [items]);

  // the sticky nav bar wraps on phones, so the map sits under whatever height it has
  useEffect(() => {
    const set = () =>
      root.current?.style.setProperty(
        "--barh",
        `${document.querySelector(".bar")?.offsetHeight ?? 0}px`,
      );
    set();
    addEventListener("resize", set);
    return () => removeEventListener("resize", set);
  }, []);
  useEffect(() => () => audio.current?.pause(), []);

  function play(url) {
    audio.current?.pause();
    if (playing === url) return setPlaying(null);
    const a = new Audio(url);
    audio.current = a;
    a.onended = () => setPlaying(null);
    setBlocked(false);
    setPlaying(url);
    a.play().catch(() => {
      setPlaying(null);
      setBlocked(true);
    });
  }

  const cur = items.find((i) => i.id === active);
  const m = mapState(cur, run);
  return (
    <div ref={root}>
      <div className="smap">
        <CorridorMap corridor={corridor} junctions={{}} phases={m.phases} vehicles={m.vehicles} />
      </div>
      <p className="muted">
        {run.vehicle_plate ?? run.id} · {vehicleLabel(run.vehicle_type, run.confirmed_tier)} ·{" "}
        {new Date(items[0].t).toLocaleString()} · run {run.id}
      </p>
      {blocked && <p className="banner">Sound is blocked by the browser. Tap Play again.</p>}
      <ol className="tl">
        {items.map((it) => (
          <li
            key={it.id}
            data-id={it.id}
            className={`si k-${it.kind}`}
            aria-current={it.id === active ? "true" : undefined}
            onClick={() => setActive(it.id)}
          >
            <div className="when">
              <time dateTime={new Date(it.t).toISOString()}>{clock(it.t)}</time>
              <span className="muted"> +{mmss((it.t - t0) / 1000)}</span>
            </div>
            <div className="card">
              <Item it={it} d={d} play={play} playing={playing} jname={jname} />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

export default function Story() {
  const runId = new URLSearchParams(location.search).get("run");
  const [s, setS] = useState({ loading: true });
  const [n, setN] = useState(0);
  useEffect(() => {
    let dead = false;
    setS({ loading: true });
    load(runId).then(
      (data) => !dead && setS({ data }),
      (e) => !dead && setS({ error: e.message || String(e) }),
    );
    return () => {
      dead = true;
    };
  }, [runId, n]);
  return (
    <div className="story">
      <Offline />
      <h2>The last run, as it happened</h2>
      <ErrCard what="the run" error={s.error} retry={() => setN((x) => x + 1)} />
      {s.loading ? (
        <p className="muted" role="status">
          Loading the last run…
        </p>
      ) : s.error ? null : !s.data ? (
        <section className="card">
          <p>
            {runId
              ? `No run ${runId} found.`
              : "No finished run with alerts yet. Play one on the Sim page, then come back."}
          </p>
          <a className="cta" href="/sim?mode=replay&autoplay=1&speed=50">
            Try the demo
          </a>
        </section>
      ) : (
        <Timeline d={s.data} />
      )}
    </div>
  );
}
