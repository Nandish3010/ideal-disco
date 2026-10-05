import { createRoot } from "react-dom/client";
import "./styles.css";
import Dispatch from "./pages/Dispatch.jsx";
import Sim from "./pages/Sim.jsx";
import Vehicle from "./pages/Vehicle.jsx";

// ponytail: path switch instead of react-router; the corridor is chosen by ?corridor=blr|hyd
const stub = () => <p className="muted">placeholder</p>;
const routes = {
  "/vehicle": ["Vehicle", Vehicle],
  "/cop": ["Cop", stub],
  "/hospital": ["Hospital", stub],
  "/control": ["Control room", stub],
  "/sim": ["Sim", Sim],
  "/dispatch": ["Dispatch", Dispatch],
};

const path = window.location.pathname.replace(/\/$/, "");
const [title, Page] = routes[path] ?? ["Emergency Green Corridor", () => <p className="muted">Pick a screen above.</p>];

createRoot(document.getElementById("root")).render(
  <>
    <header className="bar">
      <h1>{title}</h1>
      <nav>
        {Object.entries(routes).map(([p, [name]]) => (
          <a key={p} href={p} aria-current={p === path ? "page" : undefined}>{name}</a>
        ))}
      </nav>
    </header>
    <main><Page /></main>
  </>,
);
