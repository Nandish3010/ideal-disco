import { api } from "./api.js";

// Posts each tick of a scenario vehicle to /location at its time offset (divided by speed).
// start_offset_s is ignored here: one vehicle is fed on its own clock (startFeedAll applies the offsets).
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

// Runs every vehicle of a scenario together: each starts after its start_offset_s (divided by speed).
// runIds is {plate: run_id}, falling back to the scenario's own run_id. onTick gets {plate, i, n, t, status}.
export function startFeedAll({ scenario, runIds, speed, onTick, onDone }) {
  const stops = [], timers = [];
  let left = scenario.vehicles.length;
  for (const v of scenario.vehicles) {
    timers.push(setTimeout(() => {
      stops.push(startFeed({
        vehicle: v, runId: runIds?.[v.plate] ?? v.run_id, speed,
        onTick: (p) => onTick({ ...p, plate: v.plate }),
        onDone: () => { if (--left === 0) onDone(); },
      }));
    }, ((v.start_offset_s ?? 0) * 1000) / speed));
  }
  return () => { timers.forEach(clearTimeout); stops.forEach((f) => f()); };
}
