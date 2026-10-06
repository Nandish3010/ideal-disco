import { useState } from "react";
import { store } from "../ui.jsx";

// Big-type mode for the cop alert card (about 1.3x), remembered across visits.
export function useBigType() {
  const [on, setOn] = useState(() => store.get("cop_bigtype") === "1");
  return [
    on,
    () => {
      store.set("cop_bigtype", on ? "0" : "1");
      setOn(!on);
    },
  ];
}

// Haptic buzz for a new alert; silently does nothing where vibrate is missing (iOS, desktop).
export const buzz = () => {
  try {
    navigator.vibrate?.([200, 100, 200]);
  } catch {
    /* ignore */
  }
};
