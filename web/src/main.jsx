import { createRoot } from "react-dom/client";
import "./styles.css";
import Landing from "./pages/Landing.jsx";
import Cop from "./pages/Cop.jsx";
import Dispatch from "./pages/Dispatch.jsx";
import Hospital from "./pages/Hospital.jsx";
import Sim from "./pages/Sim.jsx";
import Control from "./pages/Control.jsx";
import Vehicle from "./pages/Vehicle.jsx";
import Story from "./pages/Story.jsx";
import { registerSW } from "./pwa.jsx";

// ponytail: path switch instead of react-router; the corridor is chosen by ?corridor=blr|hyd
const routes = {
  "/": ["Home", Landing],
  "/vehicle": ["Vehicle", Vehicle],
  "/cop": ["Cop", Cop],
  "/hospital": ["Hospital", Hospital],
  "/control": ["Control room", Control],
  "/sim": ["Sim", Sim],
  "/dispatch": ["Dispatch", Dispatch],
  "/story": ["Story", Story],
};

const path = window.location.pathname.replace(/\/$/, "") || "/";
const [title, Page] = routes[path] ?? [
  "Emergency Green Corridor",
  () => <p className="muted">Pick a screen above.</p>,
];
if (path === "/") document.title = "Emergency Green Corridor";
else document.title = `${title} · Emergency Green Corridor`;

if (import.meta.env.PROD) registerSW();

createRoot(document.getElementById("root")).render(
  <>
    <header className="bar">
      <h1>{path === "/" ? "Emergency Green Corridor" : title}</h1>
      <nav>
        {Object.entries(routes).map(([p, [name]]) => (
          <a key={p} href={p} aria-current={p === path ? "page" : undefined}>
            {name}
          </a>
        ))}
      </nav>
    </header>
    <main>
      <Page />
    </main>
  </>,
);
