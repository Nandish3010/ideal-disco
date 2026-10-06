import { describe, expect, it } from "vitest";
import {
  destName,
  firstWithAudio,
  handover,
  lastBrief,
  lastRouted,
  latestOpen,
  routedRun,
  sampleAlert,
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
  it("sampleAlert: the PREPARE alert with speech and the longest queue, else the newest with speech", () => {
    const a = (id, stage, jam_m, audio_url, at) => ({
      id,
      stage,
      jam_m,
      audio_url,
      created_at: `2026-10-05T${at}:00Z`,
    });
    const rows = [
      a("newest-stop", "STOP", 0, "u", "12"),
      a("short", "PREPARE", 120, "u", "11"),
      a("silent-long", "PREPARE", 900, null, "10"),
      a("long-old", "PREPARE", 520, "u", "08"),
      a("long-new", "PREPARE", 520, "u", "09"),
    ];
    expect(sampleAlert(rows).id).toBe("long-new");
    expect(sampleAlert([rows[0], rows[2]]).id).toBe("newest-stop");
    expect(sampleAlert([rows[2]])).toBeNull();
  });
  it("handover: the pinned brief for its own hospital, else the newest brief for the selected one", () => {
    const J = "Jayadeva Institute of Cardiovascular Sciences";
    const runs = [
      { id: "r1", destination: { name: J } },
      { id: "r2", destination: { name: "Apollo Hospital Bannerghatta Road" } },
      { id: "r3", destination: { name: J } },
    ];
    const brief = (id, h) => ({ id, model: "gemini", generated_at: `2026-10-05T${h}:00:00Z` });
    const briefs = [brief("r1", "09"), brief("r2", "11"), brief("r3", "10")];
    const pinned = brief("r1", "08");
    expect(handover({ pinned, pinnedRun: runs[0], briefs, runs, hospital: J }).id).toBe("r1");
    // pinned run went to Jayadeva: Apollo's desk gets Apollo's newest brief, not the pin
    const apollo = runs[1].destination.name;
    expect(handover({ pinned, pinnedRun: runs[0], briefs, runs, hospital: apollo }).id).toBe("r2");
    expect(handover({ briefs, runs, hospital: J }).id).toBe("r3");
    expect(handover({ briefs, runs, hospital: "Fortis Hospital Bannerghatta Road" })).toBeNull();
    expect(destName(undefined)).toBeNull();
  });
  it("routedRun prefers the pinned run when it has a routing", () => {
    const runs = [{ id: "n", routing: { applied: true, decided_at: "2026-10-05T09:00:00Z" } }];
    expect(routedRun({ id: "p", routing: { trace: [] } }, runs).id).toBe("p");
    expect(routedRun({ id: "p" }, runs).id).toBe("n");
    expect(routedRun(undefined, runs).id).toBe("n");
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
