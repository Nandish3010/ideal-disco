import { Fragment, createElement, useSyncExternalStore } from "react";
import en from "./en.json";
import kn from "./kn.json";
import te from "./te.json";

// Static dictionaries, no runtime translation calls. Missing keys fall back to English, then to the key itself.
const DICT = { en, kn, te };
export const LANGS = { en: "English", kn: "ಕನ್ನಡ", te: "తెలుగు" };

const read = () => {
  try {
    const l = localStorage.getItem("lang");
    return DICT[l] ? l : "en";
  } catch {
    return "en"; // private mode
  }
};
let lang = read();
const subs = new Set();

export const getLang = () => lang;
export function setLang(l) {
  if (!DICT[l] || l === lang) return;
  lang = l;
  try {
    localStorage.setItem("lang", l);
  } catch {
    /* ignore */
  }
  subs.forEach((f) => f());
}
// Re-renders the calling component when the language changes (the shell uses it, so every page re-renders).
export const useLang = () =>
  useSyncExternalStore((f) => (subs.add(f), () => subs.delete(f)), getLang);

export const has = (key) => key in en;
// t("cop.ack_label", {stage}) -> string; {name} placeholders are filled from vars.
export function t(key, vars) {
  const s = DICT[lang][key] ?? en[key] ?? key;
  return vars ? s.replace(/\{(\w+)\}/g, (m, k) => vars[k] ?? m) : s;
}

// Like t(), but {slots} are filled with React nodes (links, bold): tn("landing.step1", { link: <a/> }) -> array.
export const tn = (key, nodes) =>
  t(key)
    .split(/(\{\w+\})/)
    .map((p, i) => {
      const m = p.match(/^\{(\w+)\}$/);
      return m ? createElement(Fragment, { key: i }, nodes[m[1]]) : p;
    });
