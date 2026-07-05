import "@testing-library/jest-dom/vitest";

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
