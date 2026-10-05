import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("../firebase.js", () => ({ db: {} })); // ui.jsx imports Firestore; no config in tests
import { StateBadge, rel } from "../ui.jsx";
const css = readFileSync("src/styles.css", "utf8"); // vitest runs from web/

// Tier colours live in CSS (.tier-<tier> -> a palette variable), so check the stylesheet.
const rgb = (tier) => {
  const v = css.match(new RegExp(`\\.tier-${tier} \\{\\s*color: var\\((--[a-z]+)\\)`))[1];
  const hex = css.match(new RegExp(`${v}: #([0-9a-f]{6})`))[1];
  return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
};

describe("tier colours", () => {
  it("critical is red, urgent amber, stable green", () => {
    const [cr, cg, cb] = rgb("critical");
    expect(cr).toBeGreaterThan(cg + 100);
    expect(cr).toBeGreaterThan(cb + 100);
    const [ur, ug, ub] = rgb("urgent");
    expect(ur).toBeGreaterThan(ug);
    expect(ug).toBeGreaterThan(ub + 100);
    const [sr, sg, sb] = rgb("stable");
    expect(sg).toBeGreaterThan(sr + 100);
    expect(sg).toBeGreaterThan(sb + 50);
  });
});

describe("StateBadge", () => {
  const html = (run, now = 100_000) => renderToStaticMarkup(<StateBadge run={run} now={now} />);

  it("labels each run state", () => {
    expect(html({ state: "en_route" })).toContain(">EN ROUTE<");
    expect(html({ state: "off_route" })).toContain(">OFF ROUTE<");
    expect(html({ state: "arrived" })).toContain(">ARRIVED<");
    expect(html({})).toContain(">—<");
  });

  it("shows how stale the last tick is", () => {
    expect(html({ state: "stale", last_tick_at: 70_000 })).toContain("STALE · last tick 30 s ago");
    expect(html({ state: "stale" })).toContain("last tick ? s ago");
  });

  it("rel formats relative times", () => {
    expect(rel(97_000, 100_000)).toBe("just now");
    expect(rel(40_000, 100_000)).toBe("1 min ago");
  });
});
