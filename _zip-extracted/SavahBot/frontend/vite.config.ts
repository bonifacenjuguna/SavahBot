import { defineConfig } from "vite";

// Static single-page app. VITE_API_URL is read at build time; the login screen can also override it at runtime.
export default defineConfig({
  build: { target: "es2022", sourcemap: false },
  worker: { format: "es" },       // the neural voice runs in a module worker (src/reader-worker.ts)
  server: { port: 5173 },
});
