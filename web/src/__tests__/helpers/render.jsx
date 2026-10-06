import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, vi } from "vitest";
import { memoryStorage } from "./storage.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
vi.stubGlobal("localStorage", memoryStorage());

let root, host;
export async function mount(el) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(el));
  return host;
}
export const unmount = async () => {
  await act(async () => root?.unmount());
  host?.remove();
  root = host = null;
};
afterEach(async () => {
  await unmount();
  localStorage.clear();
});

// React-controlled input: set through the native setter so onChange fires.
export async function type(el, value) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement : HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto.prototype, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
export const click = (el) => act(async () => el.click());
export const text = (el, re) =>
  [...el.querySelectorAll("button,a")].find((b) => re.test(b.textContent));
