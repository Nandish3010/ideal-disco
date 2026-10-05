import { defineConfig } from "vite";

// ponytail: esbuild handles JSX, so no @vitejs/plugin-react dependency
export default defineConfig({ esbuild: { jsx: "automatic" } });
