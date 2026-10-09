import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Compila hacia el paquete Python, que sirve la interfaz en 127.0.0.1:2122.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../generador_rfd/static", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:2122" } },
});
