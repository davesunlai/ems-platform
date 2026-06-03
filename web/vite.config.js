import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // Pro lokální vývoj (npm run dev): API proxy na běžící backend.
    proxy: { "/api": "http://localhost:8000" },
  },
  build: { outDir: "dist" },
});
