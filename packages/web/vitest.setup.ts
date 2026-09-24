import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// `globals` is off, so Testing Library's automatic cleanup never registers
// itself — without this, each test's tree stays in the document and the next
// test's queries find two of everything.
afterEach(cleanup);

// jsdom doesn't implement ResizeObserver; SvgPreview uses it purely to
// refit the pan/zoom stage on container resize, which tests don't exercise.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (typeof globalThis.ResizeObserver === "undefined") {
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver =
    ResizeObserverStub;
}
