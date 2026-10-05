import { api } from "./api.js";

// Posts each tick of a scenario vehicle to /location at its time offset (divided by speed).
// start_offset_s is ignored: one vehicle is fed on its own clock (the scenario runner comes later).
// Errors (incl. the 501 stub) are reported through onTick and never stop the feed.
export function startFeed({ vehicle, runId, speed, onTick, onDone }) {
  let stopped = false;
  let timer;
  const t0 = Date.now();
  const n = vehicle.ticks.length;

  const step = async (i) => {
    if (stopped) return;
    const k = vehicle.ticks[i];
    let status;
    try {
      await api("/location", {
        run_id: runId, lat: k.lat, lng: k.lng, speed_mps: k.speed_mps,
        t: new Date().toISOString(), source: "sim",
      });
      status = 200;
    } catch (e) {
      status = e.status || e.message;
    }
    if (stopped) return;
    onTick({ i: i + 1, n, t: k.t, status });
    if (i + 1 >= n) return onDone();
    const wait = (vehicle.ticks[i + 1].t * 1000) / speed - (Date.now() - t0);
    timer = setTimeout(() => step(i + 1), Math.max(0, wait));
  };

  step(0);
  return () => { stopped = true; clearTimeout(timer); };
}
