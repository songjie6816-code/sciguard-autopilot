import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { renameSync } from "node:fs";

const publicApiUrl =
  process.env.SCIGUARD_PUBLIC_API_URL ??
  "https://sciguard-live-sandbox.songjie6816.workers.dev";

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
    "process.env.NEXT_PUBLIC_SCIGUARD_API_URL": JSON.stringify(publicApiUrl),
    "process.env.NEXT_PUBLIC_SCIGUARD_JUDGE_BUILD": JSON.stringify("true"),
  },
});
