import { createRoot } from "react-dom/client";

// ponytail: path switch instead of react-router; the corridor is chosen by ?corridor=blr|hyd
const stub = (name) => () => <main><h1>{name}</h1><p>placeholder</p></main>;
const routes = {
  "/vehicle": stub("Vehicle"),
  "/cop": stub("Cop"),
  "/hospital": stub("Hospital"),
  "/control": stub("Control room"),
  "/sim": stub("Sim"),
  "/dispatch": stub("Dispatch"),
};

const Page = routes[window.location.pathname.replace(/\/$/, "")] ??
  (() => <main><h1>Emergency Green Corridor</h1>
    <ul>{Object.keys(routes).map((p) => <li key={p}><a href={p}>{p}</a></li>)}</ul></main>);

createRoot(document.getElementById("root")).render(<Page />);
