import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, copTokenKey } from "../api.js";

let fetchMock, localStorage;
beforeEach(() => {
  const m = new Map(); // the runner's own localStorage is not reliable across Node versions
  localStorage = { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v) };
  vi.stubGlobal("localStorage", localStorage);
  fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({}) }));
  vi.stubGlobal("fetch", fetchMock);
});
const sent = async (path, body, token) => {
  await api(path, body, token);
  return fetchMock.mock.calls.at(-1)[1].headers["X-Device-Token"];
};

describe("X-Device-Token", () => {
  it("is the vehicle's token (from bind) on run calls, and absent when there is none", async () => {
    expect(await sent("/location", { run_id: "r" })).toBeUndefined();
    localStorage.setItem("vehicle_token", "V");
    for (const path of ["/location", "/runs", "/triage", "/log", "/runs/r/confirm"])
      expect(await sent(path, { run_id: "r" })).toBe("V");
  });

  it("is the cop's token for /duty, /cop-note and /ack, whichever junction form is sent", async () => {
    expect(copTokenKey("blr", "j3")).toBe("cop_token_blr_j3");
    expect(copTokenKey("blr", "blr_j3")).toBe("cop_token_blr_j3");
    localStorage.setItem("cop_token_blr_j3", "C");
    localStorage.setItem("vehicle_token", "V");
    expect(await sent("/duty", { corridor: "blr", junction_id: "j3", on: false })).toBe("C");
    expect(await sent("/cop-note", { corridor: "blr", junction_id: "blr_j3" })).toBe("C");
    expect(await sent("/ack", { run_id: "r", junction_id: "blr_j3" })).toBe("C");
    // another junction: no cop token, so /ack falls back to the vehicle's
    expect(await sent("/ack", { run_id: "r", junction_id: "blr_j4" })).toBe("V");
  });

  it("an explicit token wins, and an empty one sends no header", async () => {
    localStorage.setItem("vehicle_token", "V");
    expect(await sent("/location", {}, "sim")).toBe("sim");
    expect(await sent("/vehicles/bind", {}, "")).toBeUndefined();
  });
});
