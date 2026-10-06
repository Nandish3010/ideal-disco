import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import en from "../i18n/en.json";
import kn from "../i18n/kn.json";
import te from "../i18n/te.json";
import { has, setLang, t } from "../i18n/index.js";
import { memoryStorage } from "./helpers/storage.js";

vi.stubGlobal("localStorage", memoryStorage());
beforeEach(() => setLang("en"));

const slots = (s) => (s.match(/\{\w+\}/g) ?? []).sort().join();

describe("dictionaries", () => {
  for (const [name, d] of [
    ["kn", kn],
    ["te", te],
  ]) {
    it(`every key in en.json exists in ${name}.json, and nothing extra`, () => {
      expect(Object.keys(en).filter((k) => !(k in d))).toEqual([]);
      expect(Object.keys(d).filter((k) => !(k in en))).toEqual([]);
    });
    it(`${name}.json keeps the same {placeholders} as English and has no empty strings`, () => {
      for (const k of Object.keys(en)) {
        expect(slots(d[k]), k).toBe(slots(en[k]));
        expect(d[k].trim(), k).not.toBe("");
      }
    });
  }

  it("every literal t()/tn() key used in the source is in en.json", () => {
    const files = (dir) =>
      readdirSync(dir).flatMap((f) => {
        const p = join(dir, f);
        return statSync(p).isDirectory()
          ? f === "__tests__"
            ? []
            : files(p)
          : /\.jsx?$/.test(f)
            ? [p]
            : [];
      });
    const missing = [];
    for (const f of files("src"))
      for (const m of readFileSync(f, "utf8").matchAll(/\bt[n]?\(\s*"([a-z0-9_.]+)"/g))
        if (!has(m[1])) missing.push(`${f}: ${m[1]}`);
    expect(missing).toEqual([]);
  });
});

describe("t()", () => {
  it("defaults to English and fills {placeholders}", () => {
    expect(t("cop.in_min", { n: 3 })).toBe("in 3 min");
  });
  it("switches language, persists it, and falls back to the key for unknown keys", () => {
    setLang("kn");
    expect(t("cop.in_min", { n: 3 })).toBe(kn["cop.in_min"].replace("{n}", "3"));
    expect(localStorage.getItem("lang")).toBe("kn");
    expect(t("no.such.key")).toBe("no.such.key");
  });
  it("ignores an unsupported language", () => {
    setLang("xx");
    expect(t("cop.now")).toBe("now");
  });
});
