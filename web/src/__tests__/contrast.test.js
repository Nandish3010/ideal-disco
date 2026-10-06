import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Recomputes the WCAG contrast of every palette pair documented in styles.css (vitest runs from web/).
const css = readFileSync("src/styles.css", "utf8");
const cop = readFileSync("src/cop.css", "utf8");
const control = readFileSync("src/control.css", "utf8");
const tok = Object.fromEntries(
  [...css.matchAll(/--([a-z]+): (#[0-9a-f]{6});/g)].map((m) => [m[1], m[2]]),
);
// literal fills used by rules (button fill, input fill, table selection ...)
const lit = {
  btn: "#2a313b",
  field: "#0f1318",
  esc: "#4a0a0a",
  hot: "#2a1010",
  sel: "#243040",
  stale: "#59616d",
  black: "#000000",
};
const hex = (n) => tok[n] ?? lit[n];

const lin = (c) => ((c /= 255) <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const lum = (h) => {
  const n = parseInt(h.slice(1), 16);
  return 0.2126 * lin(n >> 16) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
};
const ratio = (a, b) => {
  const [x, y] = [lum(hex(a)), lum(hex(b))].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

// [foreground, background, minimum]: 4.5 for text, 3 for UI boundaries and large text
const PAIRS = [
  ["fg", "bg", 4.5],
  ["fg", "card", 4.5],
  ["fg", "btn", 4.5],
  ["fg", "field", 4.5],
  ["fg", "esc", 4.5],
  ["fg", "hot", 4.5],
  ["fg", "stale", 4.5],
  ["muted", "bg", 4.5],
  ["muted", "card", 4.5],
  ["muted", "btn", 4.5],
  ["muted", "field", 4.5],
  ["muted", "sel", 4.5],
  ["accent", "bg", 4.5],
  ["accent", "card", 4.5],
  ["accent", "sel", 4.5],
  ["accent", "btn", 4.5],
  ["bad", "bg", 4.5],
  ["bad", "card", 4.5],
  ["bad", "hot", 4.5],
  ["warn", "bg", 4.5],
  ["warn", "card", 4.5],
  ["info", "card", 4.5],
  ["info", "bg", 4.5],
  ["black", "accent", 4.5],
  ["black", "bad", 4.5],
  ["black", "warn", 4.5],
  ["black", "info", 4.5],
  ["edge", "bg", 3],
  ["edge", "card", 3],
  ["edge", "field", 3],
  ["edge", "btn", 3],
  ["edge", "sel", 3],
  ["accent", "bg", 3],
  ["accent", "card", 3], // focus ring against the page and cards
];

describe("palette contrast (WCAG AA)", () => {
  for (const [f, b, min] of PAIRS)
    it(`${f} on ${b} >= ${min}`, () => expect(ratio(f, b)).toBeGreaterThanOrEqual(min));

  it("badges that carry text use black on a light fill, not white on a mid-tone", () => {
    expect(control).toMatch(/\.cb\.s-UPDATE \{\s*background: var\(--info\);\s*color: #000;/);
    expect(control).toMatch(/\.cb\.esc-b \{\s*background: var\(--bad\);\s*color: #000;/);
  });
  it("placeholders use the muted token at full opacity", () => {
    expect(css).toMatch(/::placeholder \{\s*color: var\(--muted\);\s*opacity: 1;/);
  });
});

describe("focus and motion", () => {
  it("every focusable control gets a visible focus ring", () => {
    expect(css).toMatch(/:focus-visible \{\s*outline: 3px solid var\(--accent\);/);
    expect(css).not.toMatch(/outline: none(?!; \/\* the skip link)/);
  });
  it("reduced motion switches off animation and transitions", () => {
    expect(css).toMatch(
      /prefers-reduced-motion: reduce[\s\S]*animation: none !important[\s\S]*transition: none !important/,
    );
  });
});

describe("touch targets", () => {
  const minH = (src, sel) => {
    const m = src.match(new RegExp(`(?:^|\\n)${sel.replace(/[.[\]]/g, "\\$&")} \\{([^}]*)\\}`));
    return Number(m?.[1].match(/min-height: (\d+)px/)?.[1]);
  };
  it("ACK and Hold to report are at least 48 px", () => {
    expect(minH(cop, "button.ack")).toBeGreaterThanOrEqual(48);
    expect(minH(cop, "button.giant.report")).toBeGreaterThanOrEqual(48);
  });
  it("other cop controls are at least 44 px", () => {
    for (const sel of [".mute", "button.replay", ".duty-off"])
      expect(minH(cop, sel), sel).toBeGreaterThanOrEqual(44);
    expect(minH(css, "button")).toBeGreaterThanOrEqual(48);
  });
});
