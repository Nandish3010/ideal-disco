import { api } from "./api.js";

// Starts one scenario vehicle's run just before its first tick: an incident, POST /runs (carrying the scenario
// name so /location reads its recorded spans), and for non-fire vehicles the crew's one tap (confirmed_tier is what
// priority reads; fire vehicles carry their tier on the run). Returns {runId, warn}; a failed confirm only warns.
export async function startRun({ vehicle: x, scenarioName, corridor, destination }) {
  const { incident_id } = await api("/incidents", {
    type: x.type === "fire" ? "fire" : "medical",
    severity_note: `Scenario ${scenarioName} (synthetic)`,
  });
  const { run_id } = await api("/runs", {
    action: "start",
    plate: x.plate,
    incident_id,
    corridor,
    destination,
    scenario: scenarioName,
    source: "sim",
  });
  let warn;
  if (x.type !== "fire" && x.tier) {
    try {
      await api(`/runs/${run_id}/confirm`, { tier: x.tier });
    } catch (e) {
      warn = `confirm failed: ${e.message}`;
    }
    // demo seed: the hospital brief needs one log entry; one call, failures ignored
    if (!warn && x.type === "ambulance" && x.tier === "critical") {
      api("/log", {
        run_id,
        vehicle_type: x.type,
        kind: "form",
        text: "aspirin 300 mg given",
      }).catch(() => {});
    }
  }
  return { runId: run_id, warn };
}

// Posts each tick of a scenario vehicle to /location at its time offset (divided by speed).
// start_offset_s is ignored here: one vehicle is fed on its own clock (startFeedAll applies the offsets).
// With `begin` (async, returns {runId, warn}) the run is started right before the first tick and the clock starts after it;
// onRun(runId, warn) reports the new id, a failed begin is reported through onTick and ends that vehicle's feed.
// Errors (incl. the 501 stub) are reported through onTick and never stop the feed.
export function startFeed({ vehicle, runId, begin, speed, onTick, onDone, onRun }) {
  let stopped = false;
  let timer;
  let t0 = Date.now();
  const n = vehicle.ticks.length;

  const step = async (i) => {
    if (stopped) return;
    const k = vehicle.ticks[i];
    let status;
    try {
      await api("/location", {
        run_id: runId,
        lat: k.lat,
        lng: k.lng,
        speed_mps: k.speed_mps,
        t: new Date().toISOString(),
        source: "sim",
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

  (async () => {
    if (begin) {
      try {
        const r = await begin(vehicle);
        if (stopped) return;
        runId = r.runId;
        onRun?.(runId, r.warn);
      } catch (e) {
        if (!stopped) {
          onTick({
            i: 0,
            n,
            t: 0,
            status: `start failed: ${e.message}${e.status ? ` (HTTP ${e.status})` : ""}`,
          });
          onDone();
        }
        return;
      }
    }
    t0 = Date.now();
    step(0);
  })();
  return () => {
    stopped = true;
    clearTimeout(timer);
  };
}

// Runs every vehicle of a scenario together: each starts after its start_offset_s (divided by speed).
// runIds is {plate: run_id}, falling back to the scenario's own run_id. onTick gets {plate, i, n, t, status};
// begin / onRun(plate, runId, warn) as in startFeed.
export function startFeedAll({ scenario, runIds, begin, speed, onTick, onDone, onRun }) {
  const stops = [],
    timers = [];
  let left = scenario.vehicles.length;
  for (const v of scenario.vehicles) {
    timers.push(
      setTimeout(
        () => {
          stops.push(
            startFeed({
              vehicle: v,
              runId: runIds?.[v.plate] ?? v.run_id,
              begin,
              speed,
              onTick: (p) => onTick({ ...p, plate: v.plate }),
              onDone: () => {
                if (--left === 0) onDone();
              },
              onRun: (id, w) => onRun?.(v.plate, id, w),
            }),
          );
        },
        ((v.start_offset_s ?? 0) * 1000) / speed,
      ),
    );
  }
  return () => {
    timers.forEach(clearTimeout);
    stops.forEach((f) => f());
  };
}
