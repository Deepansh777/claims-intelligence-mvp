import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    // usePolling: file watching is unreliable over Docker bind mounts on Windows.
    watch: { usePolling: true },
    proxy: { "/api": "http://localhost:8000" },
  },
});
