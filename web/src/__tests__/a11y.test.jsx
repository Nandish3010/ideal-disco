import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";

vi.mock("../firebase.js", () => ({ db: {} }));
vi.mock("firebase/firestore", async () => (await import("./helpers/firestore.js")).firestore);

import Shell from "../a11y/Shell.jsx";
import Landing from "../pages/Landing.jsx";
import Vehicle from "../pages/Vehicle.jsx";
import Hospital from "../pages/Hospital.jsx";
import Dispatch from "../pages/Dispatch.jsx";
import Cop from "../pages/Cop.jsx";
import Control from "../pages/Control.jsx";
import Sim from "../pages/Sim.jsx";
import { setLang } from "../i18n/index.js";
import { FIX } from "./helpers/firestore.js";
import { mount } from "./helpers/render.jsx";

const PAGES = { Landing, Vehicle, Hospital, Dispatch, Cop, Control, Sim };
const routes = Object.fromEntries(
  Object.entries(PAGES).map(([n, P]) => [`/${n.toLowerCase()}`, [n, P]]),
);

// Every axe rule that runs in jsdom, any impact: serious/critical and the minor ones alike. (color-contrast needs real
// layout, so it is covered by contrast.test.js against the palette instead.)
async function violations(path, setup) {
  setup?.();
  const [name, Page] = routes[path];
  const host = await mount(<Shell routes={routes} path={path} title={name} Page={Page} />);
  const r = await axe.run(host, { rules: { "color-contrast": { enabled: false } } });
  return r.violations.map(
    (v) => `${v.impact} ${v.id}: ${v.nodes.map((n) => n.target).join(" | ")}`,
  );
}

const duty = () =>
  localStorage.setItem("cop_duty", JSON.stringify({ corridor: "blr", junction: "j3" }));
const running = () => {
  localStorage.setItem(
    "bound",
    JSON.stringify({ plate: "KA01AB1234", type: "ambulance", agency: "BBMP" }),
  );
  localStorage.setItem("run_id", "r1");
};
const escalated = () => {
  FIX["runs/r1/alerts"] = [
    { ...FIX["runs/r1/alerts"][0], created_at: { toMillis: () => Date.now() - 60_000 } },
  ];
};

describe("axe: no violations in the full shell (landmarks, headings, names, labels)", () => {
  for (const lang of ["en", "kn", "te"]) {
    for (const [name, setup] of [
      ["landing", undefined],
      ["vehicle", undefined],
      ["vehicle (bound, run active)", running],
      ["hospital", undefined],
      ["dispatch", undefined],
      ["cop (off duty)", undefined],
      ["cop (on duty, live alert)", duty],
      ["control", undefined],
      ["control (escalation)", escalated],
      ["sim", undefined],
    ]) {
      it(`${name} [${lang}]`, async () => {
        setLang(lang);
        const path = "/" + name.split(" ")[0];
        expect(await violations(path, setup)).toEqual([]);
        setLang("en");
      });
    }
  }
});
