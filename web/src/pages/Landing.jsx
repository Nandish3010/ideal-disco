import { BASE } from "../api.js";
import { corridors } from "../data.js";
import { simulate } from "../replay.js";
import scenario from "../../../data/scenarios/blr-two-vehicles.json";

// The hero figure comes from the same replay maths as /sim, computed once from the scenario, so the two always agree.
const SAVED_MIN = (simulate(scenario, corridors[scenario.corridor]).saved_s / 60).toFixed(1);

const GEMINI = [
  "Voice and photo extraction: speech, typed text or a monitor photo into a fixed schema, with no tools.",
  "ATMIST handover: the hospital brief and prep checklist, generated at ETA minus 5 minutes.",
  "Alert phrasing: the short spoken line each junction cop hears.",
  "Sequencing sentence: Gemini rewords a rule-built template into one line; the result is validated and the template is used if it fails.",
  "Cop voice notes to rule actions: a spoken report from the junction fills a fixed schema, and plain rules act on it.",
  "After-action report: a plain summary of each finished run, with the timeline built in code.",
  "Hospital routing agent: built on Agent Development Kit, with four tools and a code guard that checks its choice before it is applied.",
];

const SCREENS = [
  [
    "/vehicle",
    "Vehicle",
    "Crew binds a plate, starts a run, speaks a triage note and confirms the tier.",
  ],
  [
    "/cop",
    "Cop",
    "Junction police go on duty, hear the alert (spoken in plain English; Kannada and Telugu switchable) and ACK.",
  ],
  [
    "/hospital",
    "Hospital",
    "Countdown to arrival, live vitals, and a handover brief the team can tick off.",
  ],
  [
    "/control",
    "Control room",
    "Every run on the corridor, junction board, escalations and minutes-saved report cards.",
  ],
  [
    "/sim",
    "Sim",
    "Play the scripted scenario, or feed live GPS ticks, and watch the corridor open.",
  ],
  ["/dispatch", "Dispatch", "Issue the incident ID that a run starts from."],
];

export default function Landing() {
  return (
    <div className="landing">
      <section className="hero" aria-labelledby="hero-h">
        <h2 id="hero-h">Clear the road before the siren arrives.</h2>
        <p className="lede">
          Junction police get a spoken heads-up for every ambulance and fire engine on its way
          (police vehicles are supported), and the hospital gets the brief before arrival.
        </p>
        <p className="herofig">
          <b>{SAVED_MIN} min</b> saved on the Bengaluru two-vehicle replay{" "}
          <span className="muted">(simulated estimate on a scripted scenario)</span>
        </p>
        <a className="cta" href="/sim">
          Watch the replay
        </a>
      </section>

      <p className="lede">
        <b>The problem:</b> ambulances and fire engines lose minutes at red lights and queues, and
        junction police only find out when the siren is already there.
      </p>
      <p className="lede">
        <b>The fix:</b> a green corridor. The moment a vehicle is on its way, each junction on its
        route gets a spoken heads-up so police can open the way, and the hospital gets the patient
        brief before arrival.
      </p>

      <h2>See it in 60 seconds</h2>
      <ol className="steps">
        <li>
          Open{" "}
          <a className="inline" href="/sim?mode=replay">
            /sim
          </a>
          , press Play (Replay opens at 20x). Watch the minutes-saved counter climb.
        </li>
        <li>
          Open{" "}
          <a className="inline" href="/cop">
            /cop
          </a>{" "}
          and press Sample alert to hear what a junction cop hears.
        </li>
        <li>
          Open{" "}
          <a className="inline" href="/hospital">
            /hospital
          </a>{" "}
          and open Last handover (appears after a live run).
        </li>
      </ol>

      <h2>The six screens</h2>
      <nav className="screens" aria-label="Screens">
        {SCREENS.map(([href, name, line]) => (
          <a key={href} href={href}>
            <b>{name}</b> <span className="muted">{href}</span>
            <div>{line}</div>
          </a>
        ))}
      </nav>

      <h2>Where Gemini is used</h2>
      <ul className="gem">
        {GEMINI.map((g) => (
          <li key={g}>{g}</li>
        ))}
      </ul>

      <h2>Honest limits</h2>
      <p className="banner">
        Traffic signals are simulated behind an adapter; the demo scenario uses hand-authored
        traffic spans; patients are synthetic; no user accounts; device-scoped tokens protect
        vehicle, cop and run actions; demo endpoints are rate-limited but reachable. Minutes saved
        is a simulated estimate, not a measurement.
      </p>
      <p className="muted">
        <a className="inline" href="https://github.com/Nandish3010/ideal-disco">
          Repository
        </a>{" "}
        ·{" "}
        <a className="inline" href={`${BASE}/health`}>
          API health
        </a>
      </p>
    </div>
  );
}
