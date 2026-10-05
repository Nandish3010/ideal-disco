// Vite inlines JSON from outside web/ at build time; the repo-root data/ dir is the single source.
import blr from "../../data/corridors/blr.json";
import hyd from "../../data/corridors/hyd.json";
import scenario from "../../data/scenarios/example.json";

export const corridors = { blr, hyd };
export { scenario };
