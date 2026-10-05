import { describe, expect, it } from "vitest";
import { mmss, seqLine, traceLine } from "../format.js";

describe("traceLine", () => {
  it("prefers text and uses an arrow", () => {
    expect(traceLine({ tool: "eta_to", text: "called eta_to(Jayadeva) -> 394 s" })).toBe(
      "called eta_to(Jayadeva) → 394 s",
    );
  });
  it("falls back to tool(args) → result, then the fallback marker", () => {
    expect(
      traceLine({ tool: "list_hospitals", args: { corridor: "blr" }, result: "3 hospitals" }),
    ).toBe("called list_hospitals(blr) → 3 hospitals");
    expect(traceLine({ fallback: "offline_ai" })).toBe("fallback used (offline_ai)");
  });
});

describe("seqLine", () => {
  const runs = [
    { id: "f", vehicle_type: "fire" },
    { id: "a", vehicle_type: "ambulance", confirmed_tier: "critical" },
    { id: "b", vehicle_type: "ambulance", acuity_tier: "urgent" },
  ];
  it("lists the order and marks equal offsets as shared", () => {
    const seq = [
      { run_id: "f", offset_s: 0 },
      { run_id: "a", offset_s: 12 },
      { run_id: "b", offset_s: 12 },
    ];
    expect(seqLine(seq, runs)).toBe(
      "Fire engine → +0 s · Ambulance critical → +12 s · Ambulance urgent → +12 s (shared)",
    );
  });
  it("is empty below two vehicles", () => {
    expect(seqLine([{ run_id: "f", offset_s: 0 }], runs)).toBe("");
    expect(seqLine(undefined)).toBe("");
  });
  it("falls back to the run id for an unknown run", () => {
    expect(
      seqLine([
        { run_id: "x", offset_s: 0 },
        { run_id: "y", offset_s: 12 },
      ]),
    ).toBe("x → +0 s · y → +12 s");
  });
});

it("mmss", () => expect(mmss(394)).toBe("6:34"));
