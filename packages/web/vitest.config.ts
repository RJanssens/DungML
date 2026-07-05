import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Component tests (*.test.tsx) need a DOM (jsdom) and React's JSX transform;
// the plain *.test.ts unit tests (api/auth/etc.) run fine in the same jsdom
// environment, so we don't need to split configs.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    setupFiles: ["./vitest.setup.ts"],
  },
});
