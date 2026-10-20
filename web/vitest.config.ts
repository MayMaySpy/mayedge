import os from "node:os";
import path from "node:path";
import { defineConfig } from "vitest/config";

const storageFile = path.join(os.tmpdir(), "mayedge-vitest-localstorage");

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "node",
    setupFiles: ["./src/test/storage.ts"],
    // Node warns on the bare `localStorage` global unless this file exists. Tests still use the
    // in-memory store from the setup file, not this one.
    poolOptions: {
      forks: { execArgv: ["--localstorage-file", storageFile] },
      threads: { execArgv: ["--localstorage-file", storageFile] },
    },
  },
});
