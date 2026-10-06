import { describe, expect, it } from "vitest";
import {
  copNoteText,
  currentAlert,
  dur,
  mmss,
  plural,
  seqLine,
  shortId,
  tierLabel,
  traceLine,
  vehicleLabel,
} from "../format.js";

describe("shortId", () => {
  it("shows run ids as #xxxx", () => {
    expect(shortId("run-4f1446b1")).toBe("#4f14");
    expect(shortId("abcdef")).toBe("#abcd");
    expect(shortId(undefined)).toBe("");
  });
});

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

describe("tierLabel", () => {
  it("never shows a raw enum", () => {
    expect(tierLabel("fire_with_trapped")).toBe("trapped persons");
    expect(tierLabel("police_with_incident")).toBe("incident");
    expect(tierLabel("critical")).toBe("critical");
    expect(tierLabel("some_new_tier")).toBe("some new tier");
    expect(tierLabel(undefined)).toBe("");
  });
});

describe("vehicleLabel", () => {
  it("turns type and tier enums into labels", () => {
    expect(vehicleLabel("fire", "fire_with_trapped")).toBe("Fire engine · trapped persons");
    expect(vehicleLabel("ambulance", "critical")).toBe("Ambulance · critical");
    expect(vehicleLabel("fire", "fire")).toBe("Fire engine");
    expect(vehicleLabel("police", "police_with_incident")).toBe("Police · incident");
  });
});

describe("cop note on the vehicle page", () => {
  it("reads like a line: who, what, how long", () => {
    expect(dur(120)).toBe("2 min");
    expect(dur(90)).toBe("90 s");
    const delay = { kind: "delay", extra_seconds: 120, reason: "bus stalled" };
    expect(copNoteText(delay, "blr_j3")).toBe("Cop at J3: bus stalled, +2 min");
    expect(copNoteText({ kind: "delay", extra_seconds: null, reason: "" }, "blr_j3")).toBe(
      "Cop at J3: delay",
    );
    expect(copNoteText({ kind: "cleared", reason: "" }, "blr_j4")).toBe("Cop at J4: clear");
    expect(copNoteText({ kind: "cannot_clear", reason: "crowd" }, "blr_j4")).toBe(
      "Cop at J4: cannot clear (crowd)",
    );
    expect(copNoteText({ kind: "other", reason: "rain" }, "blr_j1")).toBe("Cop at J1: rain");
    expect(copNoteText(undefined, "blr_j1")).toBe("");
  });

  it("follows the alert at the vehicle's next junction, else the newest", () => {
    const at = (ms) => ({ toMillis: () => ms });
    const alerts = [
      { junction_id: "blr_j3", created_at: at(1), cop_note: { kind: "delay" } },
      { junction_id: "blr_j4", created_at: at(2) },
      { junction_id: "blr_j3", created_at: at(3), cop_note: { kind: "cleared" } },
    ];
    expect(currentAlert(alerts, "blr_j3").cop_note.kind).toBe("cleared");
    expect(currentAlert(alerts, "blr_j4").created_at.toMillis()).toBe(2);
    expect(currentAlert(alerts, null).created_at.toMillis()).toBe(3);
    expect(currentAlert(alerts, "blr_j9").created_at.toMillis()).toBe(3); // nothing there: the newest overall
    expect(currentAlert([], "blr_j3")).toBeUndefined();
  });
});

describe("plural", () => {
  it("agrees with the count", () => {
    expect(plural(1, "junction")).toBe("1 junction");
    expect(plural(0, "junction")).toBe("0 junctions");
    expect(plural(5, "junction")).toBe("5 junctions");
    expect(plural(2, "person", "people")).toBe("2 people");
  });
});
