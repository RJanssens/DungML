import { describe, expect, it } from "vitest";

import { initials } from "./avatar";

describe("initials", () => {
  it("takes first letters of the first two words", () => {
    expect(initials("Raf Janssens")).toBe("RJ");
    expect(initials("  ada  lovelace  king ")).toBe("AL");
  });

  it("uses first two chars of a single token", () => {
    expect(initials("raf")).toBe("RA");
    expect(initials("dev-user")).toBe("DE");
  });

  it("falls back to ? for empty input", () => {
    expect(initials("")).toBe("?");
    expect(initials("   ")).toBe("?");
  });
});
