import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../firebase.js", () => ({ db: {} }));
vi.mock("firebase/firestore", async () => (await import("./helpers/firestore.js")).firestore);

import Control from "../pages/Control.jsx";
import { PlanCard } from "../trace.jsx";
import { FIX } from "./helpers/firestore.js";
import { mount } from "./helpers/render.jsx";

const decided_at = new Date(2026, 9, 6, 14, 5, 30);
const replan = {
  plan: { action: "reroute", reason: "East approach is blocked.", confidence: 0.8 },
  action_text: "Rerouted via the alternative route (+45 s)",
  decided_at,
  trace: [
    {
      tool: "junction_state",
      text: "called junction_state(blr_j3) → 2 vehicles, queue {'E': 120} m",
    },
    { tool: "alternative_route", text: "called alternative_route(run-1) → +45 s vs current" },
  ],
};
const rejected = {
  plan: { action: "escalate", reason: "Safety check: eta_too_long." },
  action_text: "Escalated to control",
  decided_at,
  trace: [
    { tool: "alternative_route", text: "called alternative_route(run-1) → +200 s vs current" },
    {
      guard: "eta_too_long",
      text: "guard: eta_too_long (+200 s); fallback: escalate and notify control",
    },
  ],
};

describe("PlanCard", () => {
  it("shows the action, the reason, the time and each tool call", async () => {
    const h = await mount(<PlanCard replan={replan} />);
    expect(h.textContent).toContain("Re-planner · Rerouted via the alternative route (+45 s)");
    expect(h.textContent).toContain("14:05");
    expect(h.textContent).toContain("East approach is blocked.");
    expect([...h.querySelectorAll("li")].map((li) => li.textContent)).toEqual(
      replan.trace.map((e) => e.text),
    );
    expect(h.querySelector(".bad")).toBeNull();
  });

  it("shows a rejected plan's safety check note apart from the tool calls", async () => {
    const h = await mount(<PlanCard replan={rejected} />);
    expect(h.querySelector(".bad").textContent).toContain("guard: eta_too_long");
    expect(h.querySelectorAll("li")).toHaveLength(1);
    expect(h.textContent).toContain("Escalated to control");
  });

  it("falls back to the action name and renders nothing without a plan", async () => {
    let h = await mount(<PlanCard replan={{ plan: { action: "no_change" } }} />);
    expect(h.textContent).toContain("Re-planner · no_change");
    h.remove();
    for (const r of [undefined, {}, { plan: null }]) {
      h = await mount(<PlanCard replan={r} />);
      expect(h.textContent).toBe("");
      h.remove();
    }
  });
});

describe("control junction card", () => {
  const saved = FIX.junctions;
  afterEach(() => (FIX.junctions = saved));

  it("shows the junction's latest re-plan", async () => {
    FIX.junctions = saved.map((j) => ({ ...j, replan }));
    const h = await mount(<Control />);
    expect(h.textContent).toContain("Re-planner · Rerouted via the alternative route (+45 s)");
  });

  it("shows nothing extra when the junction has no re-plan", async () => {
    const h = await mount(<Control />);
    expect(h.textContent).not.toContain("Re-planner");
  });
});
