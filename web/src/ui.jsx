import { cloneElement, useEffect, useId, useRef, useState } from "react";
import { collection, doc, onSnapshot } from "firebase/firestore";
import { db } from "./firebase.js";
import { t } from "./i18n/index.js";

// localStorage can throw (private mode); fall back to memory-less defaults.
export const store = {
  get: (k) => {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  set: (k, v) => {
    try {
      v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v);
    } catch {
      /* ignore */
    }
  },
};

export function deviceId() {
  let id = store.get("device_id");
  if (!id) {
    // randomUUID needs a secure context; LAN http dev falls back
    id =
      crypto.randomUUID?.() ??
      "dev-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
    store.set("device_id", id);
  }
  return id;
}

// Live Firestore doc -> {data, loading, error, missing}
export function useDoc(path) {
  const [s, setS] = useState({ loading: !!path });
  useEffect(() => {
    if (!path) {
      setS({});
      return;
    }
    setS({ loading: true });
    return onSnapshot(
      doc(db, path),
      (d) => setS(d.exists() ? { data: d.data() } : { missing: true }),
      (e) => setS({ error: e.message }),
    );
  }, [path]);
  return s;
}

// Live runs/{id}/log -> {rows, error}. Sorted client-side by `n` (field, else doc id) so a doc missing the field is never dropped.
export function useLog(runId) {
  const [s, setS] = useState({});
  useEffect(() => {
    setS({});
    if (!runId) return;
    return onSnapshot(
      collection(db, `runs/${runId}/log`),
      (q) =>
        setS({
          rows: q.docs
            .map((d) => ({ id: d.id, ...d.data() }))
            .sort((a, b) => (a.n ?? a.id) - (b.n ?? b.id)),
        }),
      (e) => setS({ error: e.message }),
    );
  }, [runId]);
  return s;
}

export const when = (v) =>
  (v?.toDate ? v.toDate() : v ? new Date(v) : null)?.toLocaleTimeString() ?? "";

export const Err = ({ e, retry }) =>
  e ? (
    <p className="card bad" role="alert">
      {t("common.error")}: {e.message}
      {e.status ? ` (${e.status})` : ""}
      {retry && (
        <>
          {" "}
          <button onClick={retry}>{t("common.retry")}</button>
        </>
      )}
    </p>
  ) : null;

// Label + control + inline help/error. The control gets id, aria-invalid and aria-describedby; the error sits right under it.
export function Field({ label, hint, error, children }) {
  const id = useId();
  const by = [hint && `${id}-h`, error && `${id}-e`].filter(Boolean).join(" ") || undefined;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {cloneElement(children, {
        id,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": by,
      })}
      {hint && (
        <p id={`${id}-h`} className="muted field-hint">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-e`} className="field-err" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

// ---- shared UI states (loading / error / offline / stale) ----
export function useNow(step = 1000) {
  const [n, setN] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setN(Date.now()), step);
    return () => clearInterval(id);
  }, [step]);
  return n;
}

// Generic live listener -> {data, loading, error, retry}. subscribe(ok, bad) returns the unsubscribe fn.
// A Firestore listener error is terminal, so retry() re-subscribes.
export function useListen(subscribe, deps) {
  const [s, setS] = useState({ loading: true });
  const [n, setN] = useState(0);
  useEffect(() => {
    setS({ loading: true });
    return subscribe(
      (data) => setS({ data }),
      (e) => setS({ error: e.message || String(e) }),
    );
  }, [...deps, n]); // eslint-disable-line react-hooks/exhaustive-deps
  return { ...s, retry: () => setN((x) => x + 1) };
}

export const ErrCard = ({ what, error, retry }) =>
  error ? (
    <div className="card bad" role="alert">
      {t("common.load_failed", { what, error })}{" "}
      <button onClick={retry}>{t("common.retry")}</button>
    </div>
  ) : null;

// Slim top banner while the browser is offline; the page stays usable.
export function Offline() {
  const [on, setOn] = useState(navigator.onLine);
  useEffect(() => {
    const up = () => setOn(true),
      down = () => setOn(false);
    addEventListener("online", up);
    addEventListener("offline", down);
    return () => {
      removeEventListener("online", up);
      removeEventListener("offline", down);
    };
  }, []);
  return on ? null : (
    <div className="offline" role="status">
      {t("common.reconnecting")}
    </div>
  );
}

const ts = (v) => (v?.toMillis ? v.toMillis() : v ? new Date(v).getTime() : 0);
export const rel = (v, now) => {
  if (!ts(v)) return "";
  const s = Math.max(0, Math.round((now - ts(v)) / 1000));
  return s < 5
    ? t("rel.now")
    : s < 60
      ? t("rel.s", { n: s })
      : s < 3600
        ? t("rel.min", { n: Math.floor(s / 60) })
        : s < 86400
          ? t("rel.h", { n: Math.floor(s / 3600) })
          : t("rel.d", { n: Math.floor(s / 86400) });
};

// Run state badge: STALE (grey) / OFF ROUTE (amber) / ARRIVED (green) / EN ROUTE.
export const StateBadge = ({ run, now }) => {
  const s = run.state,
    tick = ts(run.last_tick_at);
  const label =
    s === "stale"
      ? t("state.stale", { s: tick ? Math.max(0, Math.round((now - tick) / 1000)) : "?" })
      : s === "off_route"
        ? t("state.off_route")
        : s === "arrived"
          ? t("state.arrived")
          : s === "en_route"
            ? t("state.en_route")
            : (s ?? "—");
  return <span className={`cb st-${s}`}>{label}</span>;
};

// ---- voice: shared by the vehicle page (triage, log) and the cop page (report)
export const MAX_S = 20;
export const b64 = (blob) =>
  new Promise((ok, no) => {
    const f = new FileReader();
    f.onload = () => ok(f.result.split(",")[1]);
    f.onerror = no;
    f.readAsDataURL(blob);
  });
// Press-and-hold recorder. onClip(blob) on release, onClip(null) when the hold was too short.
export function useHold(onClip) {
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

export const holdProps = (hold) => ({
  onPointerDown: (e) => {
    e.currentTarget.setPointerCapture?.(e.pointerId);
    hold.start();
  },
  onPointerUp: hold.stop,
  onPointerCancel: hold.stop,
  onBlur: hold.stop,
  onKeyDown: (e) => {
    if ((e.key === " " || e.key === "Enter") && !e.repeat) {
      e.preventDefault();
      hold.start();
    }
  },
  onKeyUp: (e) => {
    if (e.key === " " || e.key === "Enter") hold.stop();
  },
  onContextMenu: (e) => e.preventDefault(),
});
