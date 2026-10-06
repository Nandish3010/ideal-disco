import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../firebase.js", () => ({ db: {} }));
vi.mock("firebase/firestore", async () => (await import("./helpers/firestore.js")).firestore);

import Shell from "../a11y/Shell.jsx";
import Cop from "../pages/Cop.jsx";
import Vehicle from "../pages/Vehicle.jsx";
import Hospital from "../pages/Hospital.jsx";
import { setLang } from "../i18n/index.js";
import kn from "../i18n/kn.json";
import { FIX, push } from "./helpers/firestore.js";
import { click, mount, text, type, unmount } from "./helpers/render.jsx";

afterEach(() => setLang("en"));
const duty = () =>
  localStorage.setItem("cop_duty", JSON.stringify({ corridor: "blr", junction: "j3" }));

describe("cop ergonomics", () => {
  it("big type scales the alert card and is remembered", async () => {
    duty();
    let h = await mount(<Cop />);
    expect(h.querySelector(".alert-full.bigtype")).toBeNull();
    await click(text(h, /Big type/));
    expect(h.querySelector(".alert-full.bigtype")).not.toBeNull();
    expect(localStorage.getItem("cop_bigtype")).toBe("1");
    await unmount();
    h = await mount(<Cop />);
    expect(h.querySelector(".alert-full.bigtype")).not.toBeNull();
    expect(text(h, /Big type/).getAttribute("aria-pressed")).toBe("true");
  });

  it("announces the stage word first, in exactly one assertive region, and the card itself is not live", async () => {
    duty();
    const h = await mount(<Cop />);
    const live = h.querySelectorAll("[aria-live=assertive]");
    expect(live).toHaveLength(1);
    expect(live[0].textContent.startsWith("STOP. ")).toBe(true);
    expect(h.querySelector(".alert-full").closest("[aria-live]")).toBeNull();
  });

  it("ACK has a name that starts with ACK, and Hold to report is a button with a keyboard hint", async () => {
    duty();
    const h = await mount(<Cop />);
    expect(h.querySelector("button.ack").getAttribute("aria-label")).toMatch(/^ACK/);
    const hold = text(h, /Hold to report/);
    expect(hold.getAttribute("aria-describedby")).toBe("hold-hint");
    expect(h.querySelector("#hold-hint").textContent).toMatch(/Space or Enter/);
  });

  it("buzzes once for an alert that arrives while on duty, not for old ones", async () => {
    const vibrate = vi.fn();
    navigator.vibrate = vibrate;
    duty();
    const before = FIX["alerts"];
    await mount(<Cop />);
    expect(vibrate).not.toHaveBeenCalled(); // the 1 s old fixture alert predates going on duty
    await act(async () =>
      push("alerts", [
        ...before,
        {
          id: "2",
          run_id: "r1",
          junction_id: "blr_j3",
          stage: "PREPARE",
          text: "Next one.",
          created_at: { toMillis: () => Date.now() + 5000 },
        },
      ]),
    );
    expect(vibrate).toHaveBeenCalledTimes(1);
    expect(vibrate).toHaveBeenCalledWith([200, 100, 200]);
    push("alerts", before);
    delete navigator.vibrate;
  });

  it("does not throw where vibrate is missing", async () => {
    duty();
    expect(navigator.vibrate).toBeUndefined();
    await mount(<Cop />);
  });
});

describe("language toggle", () => {
  const routes = { "/": ["Home", () => <p>x</p>], "/cop": ["Cop", () => <p>y</p>] };
  it("defaults to English, switches, persists, and sets <html lang>", async () => {
    const h = await mount(
      <Shell routes={routes} path="/cop" title="Cop" Page={routes["/cop"][1]} />,
    );
    expect(h.querySelector("nav a").textContent).toBe("Home");
    await click(text(h, /ಕನ್ನಡ/));
    expect(localStorage.getItem("lang")).toBe("kn");
    expect(document.documentElement.lang).toBe("kn");
    expect(h.querySelector("nav a").textContent).toBe(kn["nav.home"]);
    expect(text(h, /ಕನ್ನಡ/).getAttribute("aria-pressed")).toBe("true");
  });
});

describe("coach marks", () => {
  for (const [role, Page] of [
    ["vehicle", Vehicle],
    ["cop", Cop],
    ["hospital", Hospital],
  ]) {
    it(`${role}: three tips on first visit, dismissable, remembered`, async () => {
      let h = await mount(<Page />);
      expect(h.querySelectorAll(".coach li")).toHaveLength(3);
      await click(text(h, /Got it/));
      expect(h.querySelector(".coach")).toBeNull();
      expect(localStorage.getItem(`coach_${role}`)).toBe("1");
      await unmount();
      h = await mount(<Page />);
      expect(h.querySelector(".coach")).toBeNull();
    });
  }
});

describe("forms", () => {
  it("vehicle: bad plate shows the error next to the field, marks it invalid and keeps focus there", async () => {
    const h = await mount(<Vehicle />);
    const input = h.querySelector("input");
    await type(input, "xx");
    await click(h.querySelector("form button.primary"));
    const err = h.querySelector(".field-err");
    expect(err.textContent).toMatch(/KA01AB1234/);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")).toContain(err.id);
    expect(document.activeElement).toBe(input);
  });

  it("vehicle: plate field takes focus first and uses caps, no autocorrect", async () => {
    const h = await mount(<Vehicle />);
    const input = h.querySelector("input");
    expect(input.autofocus || document.activeElement === input).toBe(true);
    expect(input.getAttribute("autocapitalize")).toBe("characters");
    expect(input.getAttribute("autocorrect")).toBe("off");
  });
});

describe("hospital run list", () => {
  it("Down/Up/Home/End move focus between inbound runs", async () => {
    const h = await mount(<Hospital />);
    const list = h.querySelector("[aria-label='Inbound ambulances']");
    const btns = [...list.querySelectorAll("button")];
    expect(btns.length).toBeGreaterThanOrEqual(2);
    const key = (el, k) =>
      act(async () =>
        el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })),
      );
    btns[0].focus();
    await key(btns[0], "ArrowDown");
    expect(document.activeElement).toBe(btns[1]);
    await key(btns[1], "ArrowUp");
    expect(document.activeElement).toBe(btns[0]);
    await key(btns[0], "End");
    expect(document.activeElement).toBe(btns.at(-1));
    await key(btns.at(-1), "Home");
    expect(document.activeElement).toBe(btns[0]);
  });
});
