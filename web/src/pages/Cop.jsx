import { useEffect, useRef, useState } from "react";
import {
  collection,
  collectionGroup,
  limit,
  onSnapshot,
  orderBy,
  query,
  where,
} from "firebase/firestore";
import { db } from "../firebase.js";
import { api } from "../api.js";
import { corridors } from "../data.js";
import { SampleAlert } from "../samples.jsx";
import { ErrCard, Offline, StateBadge, deviceId, store, useDoc, useNow, when } from "../ui.jsx";
import "../cop.css";

export const ms = (v) => v?.toMillis?.() ?? (v ? Date.parse(v) : null);

export { useNow }; // moved to ui.jsx; Hospital imports it from here

// Live en_route runs (shared with the hospital page). Single-field filter, no index needed.
export function useEnRoute() {
  const [s, setS] = useState({ runs: [], loading: true });
  const [n, setN] = useState(0);
  useEffect(() => {
    setS({ runs: [], loading: true });
    return onSnapshot(
      query(collection(db, "runs"), where("state", "==", "en_route")),
      (q) => setS({ runs: q.docs.map((d) => ({ id: d.id, ...d.data() })) }),
      (e) => setS({ runs: [], error: e.message }),
    );
  }, [n]);
  return { ...s, retry: () => setN((x) => x + 1) };
}

// ---- audio: unlocked in the on-duty tap (iOS needs a gesture), one shared element reused for every alert
const SILENT = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";
const audio = typeof Audio !== "undefined" ? new Audio() : null;
function unlock() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const c = new Ctx();
    const src = c.createBufferSource();
    src.buffer = c.createBuffer(1, 1, 22050);
    src.connect(c.destination);
    src.start(0);
    c.resume?.();
  } catch {
    /* ignore */
  }
  try {
    audio.src = SILENT;
    audio.play().catch(() => {});
  } catch {
    /* ignore */
  }
  try {
    speechSynthesis.speak(Object.assign(new SpeechSynthesisUtterance(" "), { volume: 0 }));
  } catch {
    /* ignore */
  }
}
let lock;
async function wake() {
  try {
    lock = await navigator.wakeLock.request("screen");
  } catch {
    /* unsupported or denied */
  }
}

// Silence everything: the shared element and any queued speech.
function stopSound() {
  try {
    speechSynthesis.cancel();
  } catch {
    /* ignore */
  }
  try {
    audio.pause();
  } catch {
    /* ignore */
  }
}

// One sound at a time. audio_url wins; speech is used only when there is no audio_url.
function speak(a, onBlocked) {
  stopSound();
  if (!a.audio_url) {
    try {
      speechSynthesis.speak(new SpeechSynthesisUtterance(a.text));
    } catch {
      /* ignore */
    }
    return;
  }
  // gs:// is not fetchable by a browser; the media bucket is served over https
  audio.src = a.audio_url.replace(/^gs:\/\//, "https://storage.googleapis.com/");
  audio.play().catch((e) => e.name === "NotAllowedError" && onBlocked());
}

// ---- alerts for one junction. collectionGroup(alerts) on (junction_id, created_at desc), which has an index.
// If the query throws (index missing), fall back to en_route runs + each run's alerts.
function useAlerts(jid) {
  const [s, setS] = useState({ alerts: [], mode: "collectionGroup", loading: true });
  const [n, setN] = useState(0);
  useEffect(() => {
    setS({ alerts: [], mode: "collectionGroup", loading: true });
    let subs = [];
    const row = (d) => {
      const run_id = d.ref.parent.parent.id;
      return { ...d.data(), run_id, n: d.id, key: `${run_id}/${d.id}` };
    };
    const fallback = (reason) => {
      const byRun = {},
        inner = {};
      const push = (loading = false) =>
        setS({
          mode: "active runs (collectionGroup failed: " + reason + ")",
          alerts: Object.values(byRun).flat(),
          loading,
        });
      push(true);
      subs.push(
        onSnapshot(
          query(collection(db, "runs"), where("state", "==", "en_route")),
          (q) => {
            const ids = new Set(q.docs.map((d) => d.id));
            for (const id of ids)
              if (!inner[id]) {
                inner[id] = onSnapshot(
                  collection(db, "runs", id, "alerts"),
                  (a) => {
                    byRun[id] = a.docs.map(row).filter((x) => x.junction_id === jid);
                    push();
                  },
                  () => {},
                );
              }
            for (const id of Object.keys(inner))
              if (!ids.has(id)) {
                inner[id]();
                delete inner[id];
                delete byRun[id];
                push();
              }
          },
          (e) => setS({ alerts: [], mode: "active runs", error: e.message }),
        ),
        () => Object.values(inner).forEach((f) => f()),
      );
    };
    subs.push(
      onSnapshot(
        query(
          collectionGroup(db, "alerts"),
          where("junction_id", "==", jid),
          orderBy("created_at", "desc"),
          limit(20),
        ),
        (q) => setS({ mode: "collectionGroup", alerts: q.docs.map(row) }),
        (e) => {
          subs.forEach((f) => f());
          subs = [];
          fallback(e.code || "error");
        },
      ),
    );
    return () => subs.forEach((f) => f());
  }, [jid, n]);
  return { ...s, retry: () => setN((x) => x + 1) };
}

// Fire and forget: when offline, duty stays a local-only state.
const duty_ = (corridor, junction_id, on) =>
  api("/duty", { corridor, junction_id, device_id: deviceId(), on }).catch(() => {});

const ARROW = { left: "←", straight: "↑", right: "→" };
const left = (s) =>
  s >= 60 ? `in ${Math.ceil(s / 60)} min` : s > 0 ? `in ${Math.ceil(s)} s` : "now";
const STALE_MS = 10 * 60 * 1000; // an unacked alert older than this is history, not a live call
const SOUND_MS = 2 * 60 * 1000; // audio only for alerts younger than this
const PLAYS = 3,
  GAP_MS = 20000; // at most 3 plays per alert, 20 s apart

function Current({ a, t0, now, onAck }) {
  const run = useDoc(`runs/${a.run_id}`).data;
  const tier = run?.confirmed_tier ?? run?.acuity_tier;
  const rem = Math.max(0, (a.eta_s ?? 0) - (now - t0) / 1000);
  return (
    <section className={`alert-full ${a.stage}`} aria-live="assertive">
      <div>
        <h2 className="stage">{a.stage}</h2>
        {now - t0 > 20000 || a.escalated ? <span className="pill escalated">ESCALATED</span> : null}
        <p className="alert-text">{a.text_local || a.text}</p>
        {a.text_local && <p className="alert-en">{a.text}</p>}
        <p className="muted">
          {run?.vehicle_type ?? "vehicle"}
          {tier ? ` · ${tier}` : ""}
          {run && run.state !== "en_route" ? (
            <>
              {" "}
              · <StateBadge run={run} now={now} />
            </>
          ) : null}
          {a.approach ? ` · ${a.approach} approach` : ""}
          {a.jam_m ? ` · ${a.jam_m} m queue` : ""}
        </p>
        <p className="eta" aria-live="off">
          arrives {left(rem)}
        </p>
        {a.exit_move && (
          <p className="move">
            {ARROW[a.exit_move]} turning {a.exit_move.toUpperCase()}
          </p>
        )}
      </div>
      <button className="ack" onClick={() => onAck(a)} aria-label={`Acknowledge ${a.stage} alert`}>
        ACK
      </button>
    </section>
  );
}

function Duty({ corridor, junction, onOff }) {
  const jid = `${corridor}_${junction.id}`;
  const { alerts, mode, error, loading, retry } = useAlerts(jid);
  const { runs, loading: runsLoading } = useEnRoute();
  const now = useNow();
  const [local, setLocal] = useState({});
  const [blocked, setBlocked] = useState(false);
  const [seen] = useState({}); // first-seen time for alerts whose created_at has not resolved yet
  const [onDutyAt] = useState(Date.now); // alerts created before this are shown but never spoken
  const [muted, setMuted] = useState(() => store.get("cop_muted") === "1");
  const [visible, setVisible] = useState(document.visibilityState === "visible");
  const quiet = useRef({}); // alerts silenced by mute/hide: they do not resume when sound returns

  useEffect(() => {
    wake();
    const vis = () => {
      setVisible(document.visibilityState === "visible");
      document.visibilityState === "visible" && wake();
    };
    document.addEventListener("visibilitychange", vis);
    return () => {
      document.removeEventListener("visibilitychange", vis);
      lock?.release().catch(() => {});
      stopSound();
    };
  }, []);

  const t0 = (a) => ms(a.created_at) ?? (seen[a.key] ??= Date.now());
  const sorted = [...alerts].sort((x, y) => t0(y) - t0(x) || Number(y.n) - Number(x.n));
  const acked = (a) => a.acked_at || local[a.key];
  const cur = sorted.find((a) => !acked(a) && now - t0(a) < STALE_MS);

  // Audio policy: only the newest alert, if unacked, created after going on duty and under 2 min old.
  // created_at missing means old. Any change of playKey (ack, stale, newer alert, mute, hidden) stops the sound.
  const top = sorted[0];
  const created = top && ms(top.created_at);
  const fresh =
    top && !acked(top) && created != null && created > onDutyAt && now - created < SOUND_MS;
  const playKey = fresh && !muted && visible && !quiet.current[top.key] ? top.key : null;

  useEffect(() => {
    // mute or hide silences the current alert for good; only a new alert plays again
    if ((muted || !visible) && fresh) quiet.current[top.key] = true;
  }, [muted, visible]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!playKey) return;
    let n = 0;
    const say = () => {
      speak(top, () => setBlocked(true));
      if (++n >= PLAYS) clearInterval(id);
    };
    const id = setInterval(say, GAP_MS);
    say();
    return () => {
      clearInterval(id);
      stopSound();
    };
  }, [playKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleMute = () => {
    const m = !muted;
    setMuted(m);
    store.set("cop_muted", m ? "1" : "0");
    if (m) stopSound();
  };

  async function ack(a) {
    setLocal((l) => ({ ...l, [a.key]: { s: "sent" } })); // optimistic: the cop sees it done at once
    try {
      const r = await api("/ack", {
        run_id: a.run_id,
        alert_n: Number(a.n),
        junction_id: jid,
        device_id: deviceId(),
      });
      setLocal((l) => ({ ...l, [a.key]: { s: "ok", latency: r.ack_latency_s } }));
    } catch {
      /* offline: stays "sent" */
    }
  }
  const state = (a) =>
    a.acked_at
      ? `ACKED ${when(a.acked_at)}`
      : local[a.key]?.s === "ok"
        ? `ACK${local[a.key].latency != null ? ` · ${local[a.key].latency} s` : ""}`
        : local[a.key]
          ? "sent"
          : now - t0(a) < STALE_MS
            ? "waiting"
            : "no ACK";
  const since = useDoc(`duty/${jid}`).data;
  const n = runs.filter((r) => (r.corridor ?? corridor) === corridor).length;

  return (
    <>
      <Offline />
      <button className="mute" onClick={toggleMute} aria-pressed={muted}>
        {muted ? "🔇 Sound off" : "🔊 Sound on"}
      </button>
      {muted && cur && <p className="banner pulse">SOUND OFF · ALERT ON SCREEN</p>}
      {blocked && (
        <button
          className="primary"
          onClick={() => {
            unlock();
            setBlocked(false);
          }}
        >
          Sound is blocked. Tap to enable.
        </button>
      )}
      <div aria-live="assertive">
        {cur ? (
          <Current a={cur} t0={t0(cur)} now={now} onAck={ack} />
        ) : (
          <section className="card idle" aria-live="off">
            <p className="big">On duty at {junction.name} · no vehicles approaching</p>
            <p className="eta" role="status">
              {runsLoading ? "Loading…" : `${n} en route on ${corridors[corridor].name}`}
            </p>
          </section>
        )}
      </div>
      <ErrCard what="alerts" error={error} retry={retry} />
      <SampleAlert play={speak} />
      <h2>Last alerts here</h2>
      {loading && <p className="muted">Loading…</p>}
      {!loading && !error && sorted.length === 0 && (
        <p className="muted">No alerts yet for {junction.name}</p>
      )}
      <ul className="list">
        {sorted.slice(0, 10).map((a) => (
          <li key={a.key}>
            <span className={`pill stage-${a.stage}`}>{a.stage}</span> {a.approach}{" "}
            {a.exit_move && ARROW[a.exit_move]}
            <b style={{ float: "right" }}>{state(a)}</b>
            <div className="muted">
              {when(a.created_at)} · {a.run_id}
              <button
                className="replay"
                aria-label={`Replay ${a.stage} alert`}
                onClick={() => speak(a, () => setBlocked(true))}
              >
                ▶ Replay
              </button>
            </div>
          </li>
        ))}
      </ul>
      {since && since.on !== false && (
        <p className="muted">
          On duty since {when(since.since ?? since.updated_at ?? since.created_at)}
        </p>
      )}
      <details className="muted">
        <summary>debug</summary>Feed: {mode}
      </details>
      <a
        className="duty-off"
        href="#"
        onClick={(e) => {
          e.preventDefault();
          onOff();
        }}
      >
        Off duty
      </a>
    </>
  );
}

export default function Cop() {
  const q = new URLSearchParams(location.search).get("corridor");
  let saved = null;
  try {
    saved = JSON.parse(store.get("cop_duty"));
  } catch {
    /* ignore */
  }
  const find = (c, j) => corridors[c]?.junctions.find((x) => x.id === j);
  const [duty, setDuty] = useState(
    saved && find(saved.corridor, saved.junction) && (!q || q === saved.corridor) ? saved : null,
  );
  const [corridor, setCorridor] = useState(
    corridors[q] ? q : corridors[saved?.corridor] ? saved.corridor : "blr",
  );
  const [jn, setJn] = useState(saved?.junction);
  const js = corridors[corridor].junctions;
  const j = js.find((x) => x.id === jn) ?? js[0];

  if (duty) {
    return (
      <Duty
        corridor={duty.corridor}
        junction={find(duty.corridor, duty.junction)}
        onOff={() => {
          duty_(duty.corridor, duty.junction, false);
          store.set("cop_duty", null);
          setDuty(null);
        }}
      />
    );
  }
  const go = () => {
    unlock();
    wake(); // inside the tap: audio unlock and wake lock need the gesture
    const d = { corridor, junction: j.id };
    duty_(corridor, j.id, true);
    store.set("cop_duty", JSON.stringify(d));
    setDuty(d);
  };
  return (
    <>
      <Offline />
      <label>
        Corridor
        <select value={corridor} onChange={(e) => setCorridor(e.target.value)}>
          {Object.entries(corridors).map(([k, c]) => (
            <option key={k} value={k}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Junction
        <select value={j.id} onChange={(e) => setJn(e.target.value)}>
          {js.map((x) => (
            <option key={x.id} value={x.id}>
              {x.name}
            </option>
          ))}
        </select>
      </label>
      <button className="primary giant" onClick={go}>
        GO ON DUTY at {j.name}
        <small>Turns on sound and keeps the screen awake</small>
      </button>
      <SampleAlert play={speak} />
    </>
  );
}
