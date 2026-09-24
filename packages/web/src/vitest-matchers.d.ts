// jest-dom's matchers are registered at runtime by vitest.setup.ts; this
// pulls in their *type* augmentation so `toBeInTheDocument` & friends
// typecheck in component tests.
import "@testing-library/jest-dom/vitest";
