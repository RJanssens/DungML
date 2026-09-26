import { describe, expect, it } from "vitest";

import { innermostAnchor, parseSrc } from "./sourceAnchor";

describe("parseSrc", () => {
  it("reads a line:col-line:col range", () => {
    expect(parseSrc("3:1-9:2")).toEqual([3, 1, 9, 2]);
  });
  it("rejects anything else", () => {
    expect(parseSrc("3-9")).toBeNull();
    expect(parseSrc("")).toBeNull();
  });
});

describe("innermostAnchor", () => {
  // room a spans lines 3-9; its pillar is line 6; room b and its statue
  // share line 10 (the statue starts at column 30).
  const anchors = ["3:1-9:2", "6:3-6:24", "10:1-10:48", "10:30-10:46"];

  it("picks the room when the cursor is on the room but no child", () => {
    expect(innermostAnchor(anchors, { line: 4, column: 5 })).toBe("3:1-9:2");
  });
  it("picks the nested feature over the room around it", () => {
    expect(innermostAnchor(anchors, { line: 6, column: 10 })).toBe("6:3-6:24");
  });
  it("uses columns to choose between entities on one line", () => {
    expect(innermostAnchor(anchors, { line: 10, column: 5 })).toBe("10:1-10:48");
    expect(innermostAnchor(anchors, { line: 10, column: 35 })).toBe("10:30-10:46");
  });
  it("includes both ends of a range", () => {
    expect(innermostAnchor(anchors, { line: 9, column: 2 })).toBe("3:1-9:2");
    expect(innermostAnchor(anchors, { line: 3, column: 1 })).toBe("3:1-9:2");
  });
  it("returns null outside every entity", () => {
    expect(innermostAnchor(anchors, { line: 1, column: 1 })).toBeNull();
    expect(innermostAnchor(anchors, { line: 9, column: 3 })).toBeNull();
  });
  it("ignores malformed values", () => {
    expect(innermostAnchor(["junk", "3:1-9:2"], { line: 4, column: 1 })).toBe("3:1-9:2");
  });
});
