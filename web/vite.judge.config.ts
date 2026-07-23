import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { renameSync } from "node:fs";

export default defineConfig({
  plugins: [
    react(),
    {
      name: "judge-mode-root-index",
      closeBundle() {
        renameSync("judge-dist/judge.html", "judge-dist/index.html");
      },
    },
  ],
  publicDir: "public",
  build: {
    emptyOutDir: true,
    outDir: "judge-dist",
    rollupOptions: {
      input: "judge.html",
    },
  },
  define: {
    "process.env.NEXT_PUBLIC_SCIGUARD_API_URL": JSON.stringify(""),
    "process.env.NEXT_PUBLIC_SCIGUARD_JUDGE_BUILD": JSON.stringify("true"),
  },
});
