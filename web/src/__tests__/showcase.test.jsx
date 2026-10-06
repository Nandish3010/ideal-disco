import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../firebase.js", () => ({ db: {} }));
vi.mock("firebase/firestore", async () => (await import("./helpers/firestore.js")).firestore);

import Landing from "../pages/Landing.jsx";
import { LastHandover, LastRouting } from "../samples.jsx";
import { FIX } from "./helpers/firestore.js";
import { mount } from "./helpers/render.jsx";

const JAYADEVA = "Jayadeva Institute of Cardiovascular Sciences";
const saved = { ...FIX };
afterEach(() => Object.assign(FIX, saved, { "settings/showcase": undefined }));
const Chips = () => null;

describe("landing headline", () => {
  it("leads with the critical ambulance and labels the total as a simulated baseline", async () => {
    const h = await mount(<Landing />);
    const hero = h.querySelector(".hero").textContent;
    expect(hero).toMatch(/≈ \d+\.\d min saved for the critical ambulance/);
    expect(hero).toMatch(/All 3 vehicles together: 16\.5 min \(simulated baseline\)/);
    expect(hero).toMatch(/Queue drains at 1–3 m\/s → \d+\.\d–\d+\.\d min/);
    expect(h.textContent).toContain("Replay opens at 50x");
    expect(h.textContent).not.toContain("20x");
  });
});

describe("showcase pin", () => {
  it("/vehicle shows the pinned run's routing, not the newest", async () => {
    FIX["settings/showcase"] = { run_id: "pinned" };
    FIX["runs/pinned"] = {
      routing: { destination: "Pinned Hospital", eta_s: 300, reasons: [], trace: [{ text: "a" }] },
    };
    const h = await mount(<LastRouting />);
    expect(h.textContent).toContain("Pinned Hospital");
  });

  it("/hospital shows the pinned brief only for the hospital its run went to", async () => {
    FIX["settings/showcase"] = { brief_run_id: "r1" };
    let h = await mount(<LastHandover Chips={Chips} hospital={JAYADEVA} />);
    expect(h.textContent).toContain("Chest pain, hypotensive.");
    h.remove();
    h = await mount(<LastHandover Chips={Chips} hospital="Apollo Hospital Bannerghatta Road" />);
    expect(h.textContent).not.toContain("Chest pain, hypotensive.");
  });
});
