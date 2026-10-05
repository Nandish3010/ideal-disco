// Tiny JSON POST wrapper. Throws Error(server `error` code) with .status and .body attached.
const BASE = (
  import.meta.env.VITE_API_BASE || "https://corridor-api-919512130399.asia-south1.run.app"
).replace(/\/$/, "");

export async function api(path, body) {
  let res;
  try {
    res = await fetch(BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
