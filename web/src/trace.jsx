import { mmss, seqLine, shortIds, traceLine } from "./format.js";
import { t } from "./i18n/index.js";
import { ms } from "./story.js";

// "14:05" from a Firestore timestamp, Date or ISO string; "" when there is none.
export const hhmm = (v) =>
  ms(v)
    ? new Date(ms(v)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })
    : "";

// Hospital routing decision for a run (runs.routing). Pending: the tier is confirmed but the agent has not written yet.
export function TraceCard({ routing, pending }) {
  if (!routing) return pending ? <p className="muted trace">{t("trace.choosing")}</p> : null;
  return (
    <div className="card trace">
      <h2>
        {routing.destination} · {mmss(routing.eta_s)}{" "}
        <span className="pill" title={shortIds(routing.reason)}>
          {routing.applied ? t("trace.applied") : t("trace.recommend")}
        </span>
      </h2>
      {hhmm(routing.decided_at) && <p className="muted">decided at {hhmm(routing.decided_at)}</p>}
      <ul>
        {routing.reasons?.map((r) => (
          <li key={r}>{shortIds(r)}</li>
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

// The junction's last multi-vehicle sequence (junctions/{id}.last_sequence), shown when the live phase has fewer than two vehicles.
export function LastSequence({ last, runs }) {
  const line = seqLine(last?.sequence, runs);
  return line ? (
    <div className="rat">
      <div className="muted">last sequence{hhmm(last.at) ? ` · ${hhmm(last.at)}` : ""}</div>
      <div>{line}</div>
      {last.rationale && <i>{shortIds(last.rationale)}</i>}
    </div>
  ) : null;
}

// Order of vehicles through a junction plus Gemini's one-line reason; below two vehicles it falls back to the last sequence.
export function Rationale({ phase, runs, last }) {
  const line = seqLine(phase?.sequence, runs);
  return line ? (
    <div className="rat">
      <div>{line}</div>
      {phase.rationale && <i>{shortIds(phase.rationale)}</i>}
    </div>
  ) : (
    <LastSequence last={last} runs={runs} />
  );
}

// The re-planner's latest decision for a junction (junctions/{id}.replan): what it did and why, the tools it looked at, and the
// safety check's note when its own plan was rejected and control was escalated instead.
export function PlanCard({ replan }) {
  const plan = replan?.plan;
  if (!plan) return null;
  const guard = replan.trace?.find((e) => e.guard);
  return (
    <div className="rat plan">
      <div>
        <b>Re-planner</b> · {shortIds(replan.action_text ?? plan.action)}
        {hhmm(replan.decided_at) && <span className="muted"> · {hhmm(replan.decided_at)}</span>}
      </div>
      {plan.reason && <i>{shortIds(plan.reason)}</i>}
      <ol className="muted">
        {replan.trace
          ?.filter((e) => !e.guard)
          .map((e, i) => (
            <li key={i}>{traceLine(e)}</li>
          ))}
      </ol>
      {guard && <div className="bad">{traceLine(guard)}</div>}
    </div>
  );
}
