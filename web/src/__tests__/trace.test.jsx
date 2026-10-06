import { describe, expect, it, vi } from "vitest";

vi.mock("../firebase.js", () => ({ db: {} }));
vi.mock("firebase/firestore", async () => (await import("./helpers/firestore.js")).firestore);

import { LastSequence, Rationale, TraceCard, hhmm } from "../trace.jsx";
import { mount } from "./helpers/render.jsx";

const runs = [
  { id: "f", vehicle_type: "fire", acuity_tier: "fire_with_trapped" },
  { id: "a", vehicle_type: "ambulance", acuity_tier: "critical" },
];
const two = [
  { run_id: "f", offset_s: 0 },
  { run_id: "a", offset_s: 12 },
];
const at = new Date(2026, 9, 6, 14, 5, 30);
const last = { sequence: two, rationale: "Fire engine first.", at };

describe("last sequence", () => {
  it("hhmm formats timestamps and Firestore stamps, and is empty without one", () => {
    expect(hhmm(at)).toBe("14:05");
    expect(hhmm({ toMillis: () => at.getTime() })).toBe("14:05");
    expect(hhmm(undefined)).toBe("");
  });

  it("shows the live sequence when there are two vehicles and ignores last_sequence", async () => {
    const h = await mount(
      <Rationale phase={{ sequence: two, rationale: "Live." }} runs={runs} last={last} />,
    );
    expect(h.textContent).toContain("Live.");
    expect(h.textContent).not.toContain("last sequence");
  });

  it("falls back to the last sequence, labelled with its time, below two vehicles", async () => {
    for (const phase of [null, { sequence: [{ run_id: "a", offset_s: 0 }] }]) {
      const h = await mount(<Rationale phase={phase} runs={runs} last={last} />);
      expect(h.textContent).toContain("last sequence · 14:05");
      expect(h.textContent).toContain("→ +12 s");
      expect(h.textContent).toContain("Fire engine first.");
      h.remove();
    }
  });

  it("renders nothing without a multi-vehicle last sequence", async () => {
    const h = await mount(<LastSequence last={{ sequence: [two[0]], at }} runs={runs} />);
    expect(h.textContent).toBe("");
  });
});

describe("trace card", () => {
  it("says when the hospital was decided", async () => {
    const routing = { destination: "Jayadeva", eta_s: 600, applied: true, decided_at: at };
    const h = await mount(<TraceCard routing={routing} />);
    expect(h.textContent).toContain("decided at 14:05");
  });
});
