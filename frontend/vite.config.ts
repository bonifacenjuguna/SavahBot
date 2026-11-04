import { defineConfig } from "vite";

// Static single-page app. VITE_API_URL is read at build time; the login screen can also override it at runtime.
export default defineConfig({
  build: { target: "es2022", sourcemap: false },
  server: { port: 5173 },
});
