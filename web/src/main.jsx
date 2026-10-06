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
import Shell from "./a11y/Shell.jsx";
import { t } from "./i18n/index.js";

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
  () => <p className="muted">{t("app.pick")}</p>,
];

if (import.meta.env.PROD) registerSW();

createRoot(document.getElementById("root")).render(
  <Shell routes={routes} path={path} title={title} Page={Page} />,
);
