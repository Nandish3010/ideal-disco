import { useEffect, useState } from "react";

// Register the service worker (production builds only; the dev server has no hashed assets to cache).
export function registerSW() {
  const reg = () =>
    navigator.serviceWorker.register("/sw.js").catch((e) => console.warn("sw:", e.message));
  if (!("serviceWorker" in navigator)) return;
  if (document.readyState === "complete") reg();
  else addEventListener("load", reg);
}

// Chrome fires beforeinstallprompt once, possibly before React mounts, so keep it at module level.
let saved = null;
const listeners = new Set();
addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  saved = e;
  listeners.forEach((f) => f(e));
});
addEventListener("appinstalled", () => {
  saved = null;
  listeners.forEach((f) => f(null));
});

// "Install app" button; renders nothing unless the browser says the app can be installed.
export function InstallApp() {
  const [ev, setEv] = useState(saved);
  useEffect(() => {
    listeners.add(setEv);
    return () => listeners.delete(setEv);
  }, []);
  if (!ev) return null;
  return (
    <button
      onClick={async () => {
        ev.prompt();
        await ev.userChoice;
        saved = null;
        setEv(null);
      }}
    >
      Install app
    </button>
  );
}
