import { BASE } from "../api.js";

const SCREENS = [
  [
    "/vehicle",
    "Vehicle",
    "Crew binds a plate, starts a run, speaks a triage note and confirms the tier.",
  ],
  ["/cop", "Cop", "Junction police go on duty, hear the alert in their own language and ACK."],
  [
    "/hospital",
    "Hospital",
    "Countdown to arrival, live vitals, and an AI handover brief the team can tick off.",
  ],
  [
    "/control",
    "Control room",
    "Every run on the corridor, junction board, escalations and minutes-saved report cards.",
  ],
  [
    "/sim",
    "Sim",
    "Replay recorded scenarios, or feed live GPS ticks, and watch the corridor open.",
  ],
  ["/dispatch", "Dispatch", "Issue the incident ID that a run starts from."],
];

export default function Landing() {
  return (
    <div className="landing">
      <p className="lede">
        <b>The problem:</b> ambulances, fire engines and police cars lose minutes at red lights and
        queues, and junction police only find out when the siren is already there.
      </p>
      <p className="lede">
        <b>The fix:</b> a green corridor. The moment a vehicle is on its way, each junction on its
        route gets a spoken heads-up, the signal is held green, and the hospital gets the patient
        brief before arrival.
      </p>

      <h2>See it in 60 seconds</h2>
      <ol className="steps">
        <li>
          Open{" "}
          <a className="inline" href="/sim?mode=replay">
            /sim
          </a>
          , choose Replay and press Play at 20x. Watch the minutes-saved counter climb.
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
          and read the Last handover panel (Sample handover).
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

      <p className="banner">
        Honest line: traffic and GPS signals are simulated, every patient is synthetic, and sign-in
        is demo-only. Minutes saved is a simulated estimate, not a measurement.
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
