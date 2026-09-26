import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SvgPreview } from "./SvgPreview";

// A minimal render: room a (lines 3-9) with a pillar (line 6), room b and
// its statue sharing line 10.
const SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 12" width="640" height="384"
  data-map-w="20" data-map-h="12" data-origin="top-left">
  <path class="floor" data-room="a" data-src="3:1-9:2" d="M0,0 L5,0 L5,5 Z"/>
  <g data-room="a" data-src="3:1-9:2"><line class="wall" x1="0" y1="0" x2="5" y2="0"/></g>
  <text class="label" data-src="3:1-9:2">1. A</text>
  <g class="feature-instance" data-ref="pillar" data-src="6:3-6:24"></g>
  <path class="floor" data-room="b" data-src="10:1-10:48" d="M8,0 L12,0 L12,4 Z"/>
  <g class="feature-instance" data-ref="statue" data-src="10:30-10:46"></g>
</svg>`;

function marked(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("[data-src-hl]")).map(
    (el) => `${el.tagName}:${el.getAttribute("data-room") ?? el.getAttribute("data-ref") ?? el.textContent}`,
  );
}

describe("SvgPreview source highlight", () => {
  it("marks every part of the room under the cursor", () => {
    const { container } = render(<SvgPreview svg={SVG} highlightAt={{ line: 4, column: 3 }} />);
    expect(marked(container)).toEqual(["path:a", "g:a", "text:1. A"]);
  });

  it("prefers the nested feature, and follows the cursor", () => {
    const { container, rerender } = render(
      <SvgPreview svg={SVG} highlightAt={{ line: 6, column: 8 }} />,
    );
    expect(marked(container)).toEqual(["g:pillar"]);
    rerender(<SvgPreview svg={SVG} highlightAt={{ line: 10, column: 35 }} />);
    expect(marked(container)).toEqual(["g:statue"]);
  });

  it("clears the highlight when the cursor leaves every entity", () => {
    const { container, rerender } = render(
      <SvgPreview svg={SVG} highlightAt={{ line: 4, column: 3 }} />,
    );
    rerender(<SvgPreview svg={SVG} highlightAt={{ line: 1, column: 1 }} />);
    expect(marked(container)).toEqual([]);
    expect(container.querySelector("#dungml-src-hl-style")).toBeNull();
  });
});
