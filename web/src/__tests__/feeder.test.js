import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api.js", () => ({ api: vi.fn() }));
import { api } from "../api.js";
import { startFeed, startFeedAll, startRun } from "../feeder.js";

const veh = (plate, start_offset_s, times) => ({
  plate,
  start_offset_s,
  run_id: `run-${plate}`,
  ticks: times.map((t) => ({ t, lat: 12.9, lng: 77.6, speed_mps: 10 })),
});

beforeEach(() => {
  vi.useFakeTimers();
  api.mockReset();
  api.mockResolvedValue({});
});
afterEach(() => vi.useRealTimers());

describe("startFeedAll", () => {
  it("fires ticks in time order, honouring start offsets at the speed factor", async () => {
    const scenario = { vehicles: [veh("B", 10, [0, 4]), veh("A", 0, [0, 4])] };
    const seen = [];
    startFeedAll({
      scenario,
      speed: 2,
      onTick: (p) => seen.push(p.plate + p.i),
      onDone: () => seen.push("done"),
    });
    const t0 = Date.now();
    await vi.advanceTimersByTimeAsync(0);
    expect(seen).toEqual(["A1"]); // A's first tick at once; B waits 10/2 = 5 s
    await vi.advanceTimersByTimeAsync(1999);
    expect(seen).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1); // A's second tick at 4/2 = 2 s
    await vi.advanceTimersByTimeAsync(2999);
    expect(seen).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1); // B starts at 5 s
    await vi.advanceTimersByTimeAsync(2000); // B's second tick at 7 s
    expect(seen).toEqual(["A1", "A2", "B1", "B2", "done"]);
    expect(Date.now() - t0).toBe(7000);
    expect(api.mock.calls.map((c) => c[1].run_id)).toEqual(["run-A", "run-A", "run-B", "run-B"]);
  });

  it("stop cancels vehicles that have not started yet", async () => {
    const stop = startFeedAll({
      scenario: { vehicles: [veh("A", 10, [0])] },
      speed: 1,
      onTick: () => {},
      onDone: () => {},
    });
    stop();
    await vi.advanceTimersByTimeAsync(20000);
    expect(api).not.toHaveBeenCalled();
  });
});

describe("startFeed with begin", () => {
  it("starts the run before the first tick and posts it with the new run id", async () => {
    const order = [];
    api.mockImplementation(async (path) => void order.push(path));
    const begin = vi.fn(async () => {
      order.push("begin");
      return { runId: "new-run" };
    });
    const onRun = vi.fn();
    startFeed({
      vehicle: veh("A", 0, [0]),
      begin,
      speed: 1,
      onTick: () => order.push("tick"),
      onDone: () => {},
      onRun,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(order).toEqual(["begin", "/location", "tick"]);
    expect(onRun).toHaveBeenCalledWith("new-run", undefined);
    expect(api.mock.calls[0][1].run_id).toBe("new-run");
  });

  it("a failed begin is reported once and no tick is posted", async () => {
    const onTick = vi.fn();
    const onDone = vi.fn();
    startFeed({
      vehicle: veh("A", 0, [0]),
      begin: async () => {
        throw Object.assign(new Error("boom"), { status: 500 });
      },
      speed: 1,
      onTick,
      onDone,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(onTick).toHaveBeenCalledWith(
      expect.objectContaining({ status: "start failed: boom (HTTP 500)" }),
    );
    expect(onDone).toHaveBeenCalled();
    expect(api).not.toHaveBeenCalled();
  });
});

describe("startRun demo log", () => {
  const go = (type, tier) =>
    startRun({ vehicle: { plate: "P", type, tier }, scenarioName: "s", corridor: "blr" });
  const logs = () => api.mock.calls.filter((c) => c[0] === "/log");

  it("seeds one log entry for the critical ambulance only, and ignores a failed post", async () => {
    api.mockImplementation(async (path) => {
      if (path === "/log") throw new Error("422");
      return { incident_id: "I", run_id: "R" };
    });
    expect((await go("ambulance", "critical")).runId).toBe("R");
    expect(logs()).toHaveLength(1);
    expect(logs()[0][1]).toMatchObject({ run_id: "R", text: "aspirin 300 mg given" });
    api.mockClear();
    await go("ambulance", "urgent");
    await go("fire", undefined);
    expect(logs()).toHaveLength(0);
  });
});
