// Tiny JSON POST wrapper. Throws Error(server `error` code) with .status and .body attached.
export const BASE = (
  import.meta.env.VITE_API_BASE || "https://corridor-api-919512130399.asia-south1.run.app"
).replace(/\/$/, "");

const stored = (k) => {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
};

// localStorage key of the token a cop was given on going on duty: corridor "blr", junction "j3" or "blr_j3"
export const copTokenKey = (corridor, junction) =>
  `cop_token_${corridor}_${String(junction).split("_").pop()}`;

// The device token a call carries (header X-Device-Token): the cop's for /duty and /cop-note, the cop's or else the
// vehicle's for /ack, the vehicle's (from /vehicles/bind) for the rest. Open endpoints ignore it.
function tokenFor(path, body) {
  const cop = () =>
    stored(
      copTokenKey(body?.corridor ?? String(body?.junction_id).split("_")[0], body?.junction_id),
    );
  if (path === "/duty" || path === "/cop-note") return cop();
  if (path === "/ack") return cop() ?? stored("vehicle_token");
  return stored("vehicle_token");
}

// `token` overrides the stored one (the sim feeder binds its own vehicles and carries what it was given).
export async function api(path, body, token = tokenFor(path, body)) {
  let res;
  try {
    res = await fetch(BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(token && { "X-Device-Token": token }) },
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    throw Object.assign(new Error("network_error"), { status: 0, body: null });
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    // server errors are {error}; FastAPI validation is {detail:[...]}; stubs are {todo}
    const msg = data?.error ?? (data?.todo ? "not_implemented" : `http_${res.status}`);
    throw Object.assign(new Error(msg), { status: res.status, body: data });
  }
  return data;
}
