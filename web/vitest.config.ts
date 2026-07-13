import { defineConfig } from "vitest/config";
import { resolve } from "path";
import { createAliases } from "./build-aliases.mjs";

const ROOT = resolve(__dirname);

export default defineConfig({
  resolve: {
    alias: createAliases(ROOT),
  },
  test: {
    globals: true,
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.ts"],
      exclude: ["src/**/*.test.ts"],
    },
  },
});
