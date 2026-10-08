import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  server: {
    fs: {
      allow: [
        fileURLToPath(new URL(".", import.meta.url)),
        fileURLToPath(new URL("../crates/browser-core/src/mechanics", import.meta.url)),
      ],
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "entrypoints/**/*.test.tsx"],
  },
});
