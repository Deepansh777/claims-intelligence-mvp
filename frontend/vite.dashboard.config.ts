import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The offline dashboard viewer: one IIFE script and one stylesheet, every asset inlined, written
// where the backend reads it to package single-file HTML exports.
export default defineConfig({
  plugins: [react()],
  publicDir: false,
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "../backend/app/assets/dashboard-viewer",
    emptyOutDir: true,
    assetsInlineLimit: Number.MAX_SAFE_INTEGER,
    cssCodeSplit: false,
    lib: {
      entry: "src/dashboard/standalone.tsx",
      name: "DashboardViewer",
      formats: ["iife"],
      fileName: () => "dashboard.js",
    },
    rollupOptions: { output: { assetFileNames: "dashboard[extname]" } },
  },
});
