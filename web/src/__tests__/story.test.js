import { describe, expect, it, vi } from "vitest";

vi.mock("../firebase.js", () => ({ db: {} })); // story.js imports ui.jsx, which imports Firestore
import { buildTimeline, chooseRun, mapState, presence } from "../story.js";

const T = (s) => `2026-10-05T09:${s}Z`;
const NOW = Date.parse(T("10:00"));

describe("presence", () => {
  it("is grey 'no constable' with no duty doc or when off duty", () => {
    expect(presence(undefined, [], NOW)).toEqual({ on: false, text: "no constable" });
    expect(presence({ on: false }, [], NOW).on).toBe(false);
  });
  it("shows the newest ACK and its latency", () => {
    const p = presence(
      { on: true, name: "Rao", since: T("00:00") },
      [
        { acked_at: T("08:00"), ack_latency_s: 4 },
        { acked_at: T("09:50"), ack_latency_s: 1.74 },
        { acked_at: null },
      ],
      NOW,
    );
    expect(p.text).toMatch(/^Rao · On duty since \d\d:\d\d · last ACK 10 s ago \(1\.7 s\)$/);
  });
  it("says so when nothing was ACKed yet", () => {
    expect(presence({ on: true, since: T("00:00") }, [{}], NOW).text).toMatch(/no ACK yet$/);
  });
});

describe("chooseRun", () => {
  const run = (id, type, start) => ({ id, vehicle_type: type, started_at: T(start) });
  it("prefers the newest ambulance with alerts and a brief", () => {
    const c = [
      { run: run("a", "ambulance", "01:00"), alerts: 2, brief: true },
      { run: run("b", "ambulance", "05:00"), alerts: 2, brief: false },
      { run: run("f", "fire", "09:00"), alerts: 3, brief: true },
    ];
    expect(chooseRun(c).id).toBe("a");
  });
  it("falls back to an ambulance with alerts, then any run with alerts, then null", () => {
    const b = { run: run("b", "ambulance", "05:00"), alerts: 1, brief: false };
    const f = { run: run("f", "fire", "09:00"), alerts: 1, brief: true };
    expect(chooseRun([b, f]).id).toBe("b");
    expect(chooseRun([f, { ...b, alerts: 0 }]).id).toBe("f");
    expect(chooseRun([{ ...b, alerts: 0 }])).toBeNull();
  });
});

describe("buildTimeline", () => {
  const run = {
    id: "r1",
    state: "arrived",
    started_at: T("00:00"),
    last_tick_at: T("09:00"),
    confirmed_tier: "critical",
    routing: { decided_at: T("01:00") },
  };
  const d = {
    run,
    log: [{ id: "1", t: T("00:30") }],
    alerts: [
      { id: "0", junction_id: "blr_j3", approach: "NE", created_at: T("03:00") },
      { id: "1", junction_id: "blr_j4", approach: "E", created_at: T("05:00") },
    ],
    audit: [
      {
        action: "preempt_requested",
        run_id: "r1",
        junction_id: "blr_j3",
        approach: "NE",
        at: T("02:50"),
        sequence: [{ run_id: "r1", offset_s: 0 }],
      },
      {
        action: "preempt_requested",
        run_id: "r1",
        junction_id: "blr_j3",
        approach: "NE",
        at: T("02:55"),
        sequence: [{ run_id: "r1", offset_s: 0 }],
      },
      { action: "preempt_requested", run_id: "other", junction_id: "blr_j3", at: T("02:51") },
      { action: "escalation", run_id: "r1", junction_id: "blr_j3", at: T("04:00") },
    ],
    junctions: { blr_j3: { phase: { run_ids: ["r1"], rationale: "Ambulance goes first." } } },
    brief: { generated_at: T("06:00") },
    report: { minutes_saved: 5 },
    aar: { generated_at: T("12:00") },
  };
  it("merges every source in time order, junction phase before its alert, end items last", () => {
    expect(buildTimeline(d).map((i) => i.id)).toEqual([
      "start",
      "log-1",
      "route",
      "phase-1",
      "alert-0",
      "alert-1",
      "brief",
      "arrival",
      "report",
      "aar",
    ]);
  });
  it("keeps one phase per junction and sequence, from this run only, with its rationale", () => {
    const ph = buildTimeline(d).filter((i) => i.kind === "phase");
    expect(ph).toHaveLength(1);
    expect(ph[0].rationale).toBe("Ambulance goes first.");
  });
  it("has no arrival, report or after-action for a run still moving", () => {
    const ids = buildTimeline({ run: { ...run, state: "en_route" } }).map((i) => i.id);
    expect(ids).toEqual(["start", "route"]);
  });
});

describe("mapState", () => {
  it("greens the item's junction on its approach", () => {
    expect(mapState({ jid: "blr_j3", approach: "NE" }, {}).phases.blr_j3.approach).toBe("NE");
  });
  it("puts the vehicle at the last tick on arrival only", () => {
    const run = {
      id: "r",
      vehicle_type: "ambulance",
      ticks: [
        { lat: 1, lng: 2 },
        { lat: 3, lng: 4 },
      ],
    };
    expect(mapState({ kind: "start" }, run).vehicles).toEqual([]);
    expect(mapState({ kind: "arrival" }, run).vehicles[0].lat).toBe(3);
    expect(mapState({ kind: "brief" }, run).vehicles).toEqual([]);
  });
});
