import { api } from "./api.js";

// The feeder binds each scenario vehicle itself (device_id sim-<plate>) and carries the token it gets back on every
// protected call. NOTE: a bind rotates the plate's token, so a real phone bound to the same plate gets 403 until it
// binds again; acceptable for the demo.
export const bindSim = async (plate) =>
  (await api("/vehicles/bind", { plate, device_id: `sim-${plate}` }, "")).device_token;

// Starts one scenario vehicle's run just before its first tick: bind, an incident, POST /runs (carrying the scenario
// name so /location reads its recorded spans), and for non-fire vehicles the crew's one tap (confirmed_tier is what
// priority reads; fire vehicles carry their tier on the run). Returns {runId, warn, token}; a failed confirm only warns.
export async function startRun({ vehicle: x, scenarioName, corridor, destination }) {
  const token = await bindSim(x.plate);
  const { incident_id } = await api("/incidents", {
    type: x.type === "fire" ? "fire" : "medical",
    severity_note: `Scenario ${scenarioName} (synthetic)`,
  });
  const { run_id } = await api(
    "/runs",
    {
      action: "start",
      plate: x.plate,
      incident_id,
      corridor,
      destination,
      scenario: scenarioName,
      source: "sim",
    },
    token,
  );
  let warn;
  if (x.type !== "fire" && x.tier) {
    try {
      await api(`/runs/${run_id}/confirm`, { tier: x.tier }, token);
    } catch (e) {
      warn = `confirm failed: ${e.message}`;
    }
    // demo seed: the hospital brief needs one log entry; one call, failures ignored
    if (!warn && x.type === "ambulance" && x.tier === "critical") {
      api(
        "/log",
        { run_id, vehicle_type: x.type, kind: "form", text: "aspirin 300 mg given" },
        token,
      ).catch(() => {});
    }
  }
  return { runId: run_id, warn, token };
}

// Posts each tick of a scenario vehicle to /location at its time offset (divided by speed).
// start_offset_s is ignored here: one vehicle is fed on its own clock (startFeedAll applies the offsets).
// With `begin` (async, returns {runId, warn, token}) the run is started right before the first tick and the clock starts after it;
// without it the vehicle is bound here, so the ticks of an existing run carry a valid token;
// onRun(runId, warn) reports the new id, a failed begin is reported through onTick and ends that vehicle's feed.
// Errors are reported through onTick and never stop the feed.
export function startFeed({ vehicle, runId, begin, speed, onTick, onDone, onRun }) {
  let stopped = false;
  let timer;
  let token;
  let t0 = Date.now();
  const n = vehicle.ticks.length;

  const step = async (i) => {
    if (stopped) return;
    const k = vehicle.ticks[i];
    let status;
    try {
      await api(
        "/location",
        {
          run_id: runId,
          lat: k.lat,
          lng: k.lng,
          speed_mps: k.speed_mps,
          t: new Date().toISOString(),
          source: "sim",
        },
        token,
      );
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
    try {
      if (begin) {
        const r = await begin(vehicle);
        if (stopped) return;
        runId = r.runId;
        token = r.token;
        onRun?.(runId, r.warn);
      } else {
        token = await bindSim(vehicle.plate);
        if (stopped) return;
      }
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
