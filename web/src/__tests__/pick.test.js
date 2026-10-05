import { describe, expect, it } from "vitest";
import {
  firstWithAudio,
  lastBrief,
  lastRouted,
  latestOpen,
  typeLabel,
  within,
  withMethod,
} from "../pick.js";

describe("pick", () => {
  it("firstWithAudio skips null audio", () => {
    expect(
      firstWithAudio([{ id: 1 }, { id: 2, audio_url: "u" }, { id: 3, audio_url: "v" }]).id,
    ).toBe(2);
    expect(firstWithAudio([{ audio_url: null }])).toBeNull();
  });
  it("lastBrief ignores offline stubs and takes the newest", () => {
    const rows = [
      { id: "a", model: "gemini", generated_at: "2026-10-05T09:00:00Z" },
      { id: "b", model: "gemini", generated_at: "2026-10-05T10:00:00Z" },
      { id: "c", model: "offline", generated_at: "2026-10-05T11:00:00Z" },
    ];
    expect(lastBrief(rows).id).toBe("b");
    expect(lastBrief([rows[2]])).toBeNull();
  });
  it("lastRouted wants applied or a multi-step trace", () => {
    const runs = [
      { id: "x", routing: { applied: false, trace: [{}], decided_at: "2026-10-05T12:00:00Z" } },
      { id: "y", routing: { applied: true, decided_at: "2026-10-05T09:00:00Z" } },
      { id: "z", routing: { applied: false, trace: [{}, {}], decided_at: "2026-10-05T10:00:00Z" } },
      { id: "n" },
    ];
    expect(lastRouted(runs).id).toBe("z");
    expect(lastRouted([runs[0], runs[3]])).toBeNull();
  });
  it("within keeps the last 24 h only", () => {
    const now = Date.parse("2026-10-06T00:00:00Z");
    const rows = [
      { id: 1, created_at: "2026-10-05T12:00:00Z" },
      { id: 2, created_at: "2026-10-04T12:00:00Z" },
      { id: 3 },
    ];
    expect(within(rows, now).map((r) => r.id)).toEqual([1]);
  });
  it("typeLabel folds to medical / fire / police", () => {
    expect(["fire", "police", "cardiac", "medical", undefined].map(typeLabel)).toEqual([
      "fire",
      "police",
      "medical",
      "medical",
      "medical",
    ]);
  });
  it("latestOpen picks the newest open incident", () => {
    const rows = [
      { id: "a", state: "open", created_at: "2026-10-05T09:00:00Z" },
      { id: "b", state: "open", created_at: "2026-10-05T10:00:00Z" },
      { id: "c", state: "closed", created_at: "2026-10-05T11:00:00Z" },
    ];
    expect(latestOpen(rows).id).toBe("b");
  });
  it("withMethod hides reports without a method", () => {
    expect(
      withMethod([{ id: 1 }, { id: 2, method: "simulated-baseline" }]).map((r) => r.id),
    ).toEqual([2]);
  });
});
