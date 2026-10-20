import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const root = path.dirname(fileURLToPath(import.meta.url));
// Docker publishes the desk on :14200. `uv run mayedge` binds :8000 — point here with
// MAYEDGE_BACKEND=http://127.0.0.1:8000 npm run dev
const backend = process.env.MAYEDGE_BACKEND || "http://127.0.0.1:14200";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(root, "./src"),
    },
  },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: "react",
              test: /node_modules[/\\](react|react-dom|scheduler)[/\\]/,
              priority: 30,
            },
            {
              name: "lightweight-charts",
              test: /node_modules[/\\]lightweight-charts[/\\]/,
              priority: 25,
            },
            {
              name: "ui",
              test: /node_modules[/\\](@base-ui[/\\]react|radix-ui|@radix-ui|lucide-react|sonner|class-variance-authority|clsx|tailwind-merge)[/\\]/,
              priority: 20,
            },
          ],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/ws": {
        target: backend,
        changeOrigin: true,
        ws: true,
        rewriteWsOrigin: true,
      },
    },
  },
});
