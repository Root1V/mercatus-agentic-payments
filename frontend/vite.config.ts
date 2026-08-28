import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    // Evita CORS en dev: el frontend llama a rutas relativas /api/... y Vite
    // las reenvía al backend nativo (`uv run agent-commerce dashboard`).
    // En producción (Docker), nginx hace el mismo proxy (ver frontend/nginx.conf).
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
