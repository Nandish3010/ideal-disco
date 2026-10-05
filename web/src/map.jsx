import { useEffect, useRef, useState } from "react";

// Shared corridor map. Props:
//   corridor   data/corridors/*.json object (junction + approach geometry, hospital)
//   junctions  {docId: firestore junction doc}, docId = `${corridor.id}_${junction.id}` (bare id also accepted)
//   phases     optional {docId: phase} that wins over junctions[docId].phase
//   vehicles   [{id, type: ambulance|fire|police, lat, lng, stale?}]  (stale: grey, frozen marker)
//   spans      {junction_id: [{from_m,to_m,speed}]} (or a recorded [{ts, intervals}] list: latest snapshot is used);
//              from_m/to_m are metres along the approach polyline from its origin to the stop line (route order)
//   onReady    called with the google.maps.Map once created (never called by the SVG fallback)
// Without VITE_MAPS_BROWSER_KEY (or if Maps fails to load) a plain SVG drawing is rendered instead.

const KEY = import.meta.env.VITE_MAPS_BROWSER_KEY;
export const HAS_MAPS_KEY = !!KEY;
const SPEED = { NORMAL: "#8a94a3", SLOW: "#ffb020", TRAFFIC_JAM: "#ff4d4d" };
const GREEN = "#3ddc84",
  GREY = "#8a94a3";
const VEH = { ambulance: ["#e11d48", "A"], fire: ["#f97316", "F"], police: ["#3b82f6", "P"] };
const DARK = [
  { elementType: "geometry", stylers: [{ color: "#1d2430" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#8a94a3" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#0b0d10" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#2c3544" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#3a4558" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#0b0d10" }] },
  { featureType: "poi", stylers: [{ visibility: "off" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
];

// ---- geometry (pure; shared by both renderers) ----
const rad = Math.PI / 180;
// equirectangular: fine at junction scale
const dist = (a, b) =>
  Math.hypot((b[1] - a[1]) * Math.cos(((a[0] + b[0]) / 2) * rad), b[0] - a[0]) * rad * 6371000;
const lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];

// Sub-path of an approach polyline between d0..d1 metres from the junction along the reversed polyline.
export function slice(poly, d0, d1) {
  const p = [...poly].reverse(),
    out = [];
  let acc = 0;
  for (let i = 0; i < p.length - 1 && acc < d1; i++) {
    const len = dist(p[i], p[i + 1]),
      s = acc;
    acc += len;
    if (acc <= d0 || !len) continue;
    if (!out.length) out.push(lerp(p[i], p[i + 1], Math.max(0, (d0 - s) / len)));
    out.push(lerp(p[i], p[i + 1], Math.min(1, (d1 - s) / len)));
  }
  return out;
}

const ms = (v) => (v?.toMillis ? v.toMillis() : v ? new Date(v).getTime() : 0);
const intervals = (a) => (!a?.length ? [] : a[0].intervals ? a.at(-1).intervals : a);

function scene({ corridor, junctions, phases, spans, vehicles }, now) {
  const lines = [],
    dots = [];
  for (const j of corridor.junctions ?? []) {
    const key = `${corridor.id}_${j.id}`;
    const phase =
      phases?.[key] ?? phases?.[j.id] ?? junctions?.[key]?.phase ?? junctions?.[j.id]?.phase;
    dots.push({
      key,
      lat: j.lat,
      lng: j.lng,
      title: j.name,
      fill: ms(phase?.until) > now ? GREEN : GREY,
      text: phase?.approach ?? j.id.replace(/\D/g, ""),
    });
    const iv = intervals(spans?.[key] ?? spans?.[j.id]);
    for (const a of j.approaches ?? []) {
      lines.push({ path: a.polyline, color: SPEED.NORMAL, w: 4 });
      const polyLen = a.polyline.reduce(
        (sum, p, i, arr) => (i > 0 ? sum + dist(arr[i - 1], p) : 0),
        0,
      );
      for (const s of iv) {
        if (!SPEED[s.speed] || s.speed === "NORMAL") continue;
        // Convert from route order (0 at approach origin, max at stop line) to junction-from distances
        const d0 = polyLen - s.to_m;
        const d1 = polyLen - s.from_m;
        const path = slice(a.polyline, d0, d1);
        if (path.length) lines.push({ path, color: SPEED[s.speed], w: 7 });
      }
    }
  }
  const veh = (vehicles ?? [])
    .filter((v) => Number.isFinite(v.lat) && Number.isFinite(v.lng))
    .map((v) => ({
      id: v.id,
      lat: v.lat,
      lng: v.lng,
      fill: v.stale ? GREY : (VEH[v.type] ?? ["#ddd", "?"])[0],
      text: (VEH[v.type] ?? ["", "?"])[1],
      title: `${v.type ?? "vehicle"} ${v.id}${v.stale ? " (stale)" : ""}`,
    }));
  return { lines, dots, veh, hospital: corridor.hospital };
}

const icon = (fill, text, { fg = "#000", square = false, size = 32 } = {}) =>
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 32 32">` +
      (square
        ? `<rect x="2" y="2" width="28" height="28" rx="5" fill="${fill}" stroke="#fff" stroke-width="2"/>`
        : `<circle cx="16" cy="16" r="14" fill="${fill}" stroke="#fff" stroke-width="2"/>`) +
      `<text x="16" y="21.5" text-anchor="middle" font-size="16" font-weight="700" font-family="sans-serif" fill="${fg}">${text}</text></svg>`,
  );

// ---- Maps JS loader: one script tag per page ----
let loading;
function loadMaps() {
  loading ??= new Promise((resolve, reject) => {
    if (window.google?.maps?.importLibrary) return resolve();
    window.__gmReady = resolve;
    const s = document.createElement("script");
    s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(KEY)}&loading=async&libraries=geometry&callback=__gmReady`;
    s.async = true;
    s.onerror = () => reject(new Error("maps_script_failed"));
    document.head.appendChild(s);
  }).then(() =>
    Promise.all(["maps", "marker", "geometry"].map((l) => google.maps.importLibrary(l))),
  );
  return loading;
}

// re-render every few seconds so a phase whose `until` has passed turns grey
const useNow = (every = 3000) => {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), every);
    return () => clearInterval(t);
  }, [every]);
  return now;
};

function GMap({ onReady, onFail, ...props }) {
  const el = useRef(),
    g = useRef({ over: [], veh: new Map() });
  const [ready, setReady] = useState(false);
  const sc = scene(props, useNow());
  const sig = JSON.stringify([sc.lines, sc.dots, sc.hospital]);
  const vsig = JSON.stringify(sc.veh);

  useEffect(() => {
    let dead = false;
    window.gm_authFailure = onFail; // bad/blocked key: Maps calls this after loading
    loadMaps()
      .then(() => {
        if (dead) return;
        g.current.map = new google.maps.Map(el.current, {
          center: { lat: 12.92, lng: 77.61 },
          zoom: 13,
          styles: DARK,
          backgroundColor: "#0b0d10",
          disableDefaultUI: true,
          zoomControl: true,
          gestureHandling: "greedy",
        });
        setReady(true);
        onReady?.(g.current.map);
      })
      .catch((e) => {
        console.warn("Maps unavailable, using SVG fallback:", e.message);
        onFail();
      });
    return () => {
      dead = true;
    };
  }, []);

  // junctions, approach lines, hospital: rebuilt only when their content changes
  useEffect(() => {
    if (!ready) return;
    const { map, over } = g.current,
      G = google.maps;
    over.splice(0).forEach((o) => o.setMap(null));
    const pt = ([lat, lng]) => ({ lat, lng });
    const mark = (lat, lng, url, size, title, zIndex) =>
      new G.Marker({
        map,
        position: { lat, lng },
        title,
        zIndex,
        icon: { url, scaledSize: new G.Size(size, size), anchor: new G.Point(size / 2, size / 2) },
      });
    sc.lines.forEach((l, i) =>
      over.push(
        new G.Polyline({
          map,
          path: l.path.map(pt),
          strokeColor: l.color,
          strokeWeight: l.w,
          strokeOpacity: 0.95,
          zIndex: l.w,
        }),
      ),
    );
    sc.dots.forEach((d) =>
      over.push(mark(d.lat, d.lng, icon(d.fill, d.text, { size: 34 }), 34, d.title, 20)),
    );
    if (sc.hospital)
      over.push(
        mark(
          sc.hospital.lat,
          sc.hospital.lng,
          icon("#fff", "H", { fg: "#e11d48", square: true, size: 36 }),
          36,
          sc.hospital.name,
          30,
        ),
      );
  }, [ready, sig]);

  // vehicles: markers keyed by id, moved in place
  useEffect(() => {
    if (!ready) return;
    const { map, veh } = g.current,
      G = google.maps;
    const seen = new Set();
    for (const v of sc.veh) {
      seen.add(v.id);
      const pos = { lat: v.lat, lng: v.lng };
      const m = veh.get(v.id);
      const ic = {
        url: icon(v.fill, v.text, { fg: "#fff", size: 38 }),
        scaledSize: new G.Size(38, 38),
        anchor: new G.Point(19, 19),
      };
      if (m) {
        m.setPosition(pos);
        m.setTitle(v.title);
        if (m.fill !== v.fill) {
          m.setIcon(ic);
          m.fill = v.fill;
        }
      } // stale turns the marker grey
      else
        veh.set(
          v.id,
          Object.assign(
            new G.Marker({ map, position: pos, title: v.title, zIndex: 40, icon: ic }),
            { fill: v.fill },
          ),
        );
    }
    for (const [id, m] of veh)
      if (!seen.has(id)) {
        m.setMap(null);
        veh.delete(id);
      }
  }, [ready, vsig]);

  // fit to the corridor when it changes, not on every update
  useEffect(() => {
    if (!ready) return;
    const b = new google.maps.LatLngBounds();
    sc.lines.forEach((l) => l.path.forEach(([lat, lng]) => b.extend({ lat, lng })));
    sc.dots.forEach((d) => b.extend({ lat: d.lat, lng: d.lng }));
    if (sc.hospital) b.extend(sc.hospital);
    if (!b.isEmpty()) g.current.map.fitBounds(b, 40);
  }, [ready, props.corridor.id]);

  return <div ref={el} className="cmap" />;
}

// ponytail: plain equirectangular drawing; no pan/zoom
function SvgMap(props) {
  const sc = scene(props, useNow());
  const pts = [
    ...sc.lines.flatMap((l) => l.path),
    ...sc.dots.map((d) => [d.lat, d.lng]),
    ...(sc.hospital ? [[sc.hospital.lat, sc.hospital.lng]] : []),
    ...sc.veh.map((v) => [v.lat, v.lng]),
  ];
  const lats = pts.map((p) => p[0]),
    lngs = pts.map((p) => p[1]);
  const [minLat, maxLat, minLng, maxLng] = [
    Math.min(...lats),
    Math.max(...lats),
    Math.min(...lngs),
    Math.max(...lngs),
  ];
  const k = Math.cos(((minLat + maxLat) / 2) * rad),
    W = 800,
    H = 520,
    pad = 36;
  const w = Math.max((maxLng - minLng) * k, 1e-6),
    h = Math.max(maxLat - minLat, 1e-6),
    s = Math.min((W - 2 * pad) / w, (H - 2 * pad) / h);
  const X = (lng) => (W - w * s) / 2 + (lng - minLng) * k * s,
    Y = (lat) => (H - h * s) / 2 + (maxLat - lat) * s;
  const P = ([lat, lng]) => `${X(lng).toFixed(1)},${Y(lat).toFixed(1)}`;
  const dot = (key, lat, lng, r, fill, fg, text, title, sq) => (
    <g key={key}>
      <title>{title}</title>
      {sq ? (
        <rect
          x={X(lng) - r}
          y={Y(lat) - r}
          width={2 * r}
          height={2 * r}
          rx="4"
          fill={fill}
          stroke="#fff"
          strokeWidth="2"
        />
      ) : (
        <circle cx={X(lng)} cy={Y(lat)} r={r} fill={fill} stroke="#fff" strokeWidth="2" />
      )}
      <text x={X(lng)} y={Y(lat) + 5} textAnchor="middle" fontSize="14" fontWeight="700" fill={fg}>
        {text}
      </text>
    </g>
  );
  return (
    <svg
      className="cmap"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="Corridor map (no Maps key: schematic)"
      preserveAspectRatio="xMidYMid meet"
    >
      <rect width={W} height={H} fill="#1d2430" />
      {sc.lines.map((l, i) => (
        <polyline
          key={i}
          points={l.path.map(P).join(" ")}
          fill="none"
          stroke={l.color}
          strokeWidth={l.w}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
      {sc.dots.map((d) => dot(d.key, d.lat, d.lng, 13, d.fill, "#000", d.text, d.title))}
      {sc.hospital &&
        dot(
          "hosp",
          sc.hospital.lat,
          sc.hospital.lng,
          14,
          "#fff",
          "#e11d48",
          "H",
          sc.hospital.name,
          true,
        )}
      {sc.veh.map((v) => dot("v" + v.id, v.lat, v.lng, 15, v.fill, "#fff", v.text, v.title))}
    </svg>
  );
}

export default function CorridorMap(props) {
  const [failed, setFailed] = useState(false);
  if (!props.corridor) return null;
  return KEY && !failed ? (
    <GMap {...props} onFail={() => setFailed(true)} />
  ) : (
    <SvgMap {...props} />
  );
}
