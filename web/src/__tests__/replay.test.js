import { describe, expect, it } from "vitest";
import {
  blendedEta,
  clearSeconds,
  jamMetres,
  lead,
  savedRange,
  simulate,
  stage,
} from "../replay.js";
import blr from "../../../data/corridors/blr.json";
import scenario from "../../../data/scenarios/blr-two-vehicles.json";

// Mirrors the asserts at the bottom of api/leadtime.py.
const iv = (from_m, to_m, speed) => ({ from_m, to_m, speed });
const jam = (m) => [iv(0, 600 - m, "NORMAL"), iv(600 - m, 600, "TRAFFIC_JAM")];

describe("lead time maths", () => {
  it("jamMetres counts jam fully and slow half, stopping at the first clear span from the far end", () => {
    expect(jamMetres(jam(500))).toBe(500);
    expect(jamMetres([])).toBe(0);
    const mixed = [
      iv(0, 100, "TRAFFIC_JAM"),
      iv(100, 200, "NORMAL"),
      iv(200, 300, "SLOW"),
      iv(300, 400, "TRAFFIC_JAM"),
    ];
    expect(jamMetres(mixed)).toBe(150);
  });

  it("clearSeconds grows with the jam and has a 20 s reaction floor", () => {
    expect(clearSeconds(500)).toBeGreaterThan(clearSeconds(100));
    expect(clearSeconds(0)).toBe(20);
  });

  it("blendedEta floors observed speed at 3 m/s", () => {
    expect(blendedEta(100, 300, 0)).toBe(0.5 * 100 + 0.5 * 100);
  });

  it("stage thresholds: STOP <= 30 s, PREPARE within clear + buffer, else null", () => {
    expect(stage(300, clearSeconds(500))).toBeNull();
    expect(stage(270, clearSeconds(500))).toBe("PREPARE");
    expect(stage(100, clearSeconds(100))).toBeNull();
    expect(stage(30, clearSeconds(100))).toBe("STOP");
  });
});

describe("simulate()", () => {
  // Baseline is api/report.py's: per passed junction, stop = cycle_s / 4 + jam_m / 2.0, jam from the recorded spans.
  it("is deterministic and saves 988 s (16.5 min) on blr-two-vehicles", () => {
    const a = simulate(scenario, blr);
    expect(simulate(scenario, blr).saved_s).toBe(a.saved_s);
    expect(a.saved_s).toBeCloseTo(988, 6);
    expect(a.vehicles.map((v) => Math.round(v.saved_s))).toEqual([473, 30, 485]);
  });
});

describe("headline numbers", () => {
  it("leads with the critical ambulance, not the three-vehicle total", () => {
    const sim = simulate(scenario, blr);
    const v = lead(sim);
    expect([v.type, v.tier]).toEqual(["ambulance", "critical"]);
    expect(v.saved_s).toBeLessThan(sim.saved_s);
    expect(simulate(scenario, blr, 2).saved_s).toBe(sim.saved_s); // 2 m/s is the default drain rate
  });

  it("savedRange re-runs the baseline at 1 and 3 m/s and brackets the headline", () => {
    const [lo, hi] = savedRange(scenario, blr);
    const mid = lead(simulate(scenario, blr)).saved_s / 60;
    expect(lo).toBeLessThan(mid);
    expect(mid).toBeLessThan(hi);
    expect(lo).toBeCloseTo(lead(simulate(scenario, blr, 3)).saved_s / 60, 9);
    expect(hi).toBeCloseTo(lead(simulate(scenario, blr, 1)).saved_s / 60, 9);
  });
});
