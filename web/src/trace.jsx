import { mmss, seqLine, traceLine } from "./format.js";
import { t } from "./i18n/index.js";

// Hospital routing decision for a run (runs.routing). Pending: the tier is confirmed but the agent has not written yet.
export function TraceCard({ routing, pending }) {
  if (!routing) return pending ? <p className="muted trace">{t("trace.choosing")}</p> : null;
  return (
    <div className="card trace">
      <h2>
        {routing.destination} · {mmss(routing.eta_s)}{" "}
        <span className="pill" title={routing.reason}>
          {routing.applied ? t("trace.applied") : t("trace.recommend")}
        </span>
      </h2>
      <ul>
        {routing.reasons?.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      <ol className="muted">
        {routing.trace?.map((e, i) => (
          <li key={i}>{traceLine(e)}</li>
        ))}
      </ol>
    </div>
  );
}

// Order of vehicles through a junction plus Gemini's one-line reason; hidden below two vehicles.
export function Rationale({ phase, runs }) {
  const line = seqLine(phase?.sequence, runs);
  return line ? (
    <div className="rat">
      <div>{line}</div>
      {phase.rationale && <i>{phase.rationale}</i>}
    </div>
  ) : null;
}
