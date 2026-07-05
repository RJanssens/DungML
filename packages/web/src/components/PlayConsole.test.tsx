import { render, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import * as api from "../lib/api";

// Capture the props SvgPreview is mounted with, so the focusTarget tests can
// assert on exactly what PlayConsole passes down without depending on
// SvgPreview's own focus/zoom rendering.
const seen: { focusTarget?: string | null; svg?: string | null } = {};
vi.mock("./SvgPreview", () => ({
  SvgPreview: (p: { focusTarget?: string | null; svg?: string | null }) => {
    seen.focusTarget = p.focusTarget;
    seen.svg = p.svg;
    return <div data-testid="svg-preview" />;
  },
}));

import { PlayConsole } from "./PlayConsole";

afterEach(() => {
  vi.restoreAllMocks();
  seen.focusTarget = undefined;
  seen.svg = undefined;
});

test("campaign mode polls renderUrl and shows the SVG, no session calls", async () => {
  const SVG = "<svg><g id='x'/></svg>";
  const fetchSvg = vi.spyOn(api, "fetchRenderSvg").mockResolvedValue(SVG);
  const sessGet = vi.spyOn(api.sessions, "get");

  render(
    <PlayConsole mapId="m1" renderUrl="/instances/7/map/render?view=player" playerView />,
  );

  await waitFor(() =>
    expect(fetchSvg).toHaveBeenCalledWith("/instances/7/map/render?view=player"),
  );
  // The fetched SVG must actually propagate into campaignSvg → SvgPreview's svg prop.
  await waitFor(() => expect(seen.svg).toBe(SVG));

  expect(sessGet).not.toHaveBeenCalled();
});

test("passes the SVG's data-party-node as focusTarget in campaign mode", async () => {
  vi.spyOn(api, "fetchRenderSvg").mockResolvedValue(
    '<svg data-party-node="room.foyer" viewBox="0 0 10 10"></svg>',
  );

  render(<PlayConsole mapId="m1" renderUrl="/x/render?view=player" />);

  await waitFor(() => expect(seen.focusTarget).toBe("room.foyer"));
});

test("unescapes the SVG's data-party-node so it matches the decoded DOM attribute", async () => {
  vi.spyOn(api, "fetchRenderSvg").mockResolvedValue(
    '<svg data-party-node="room.Kitchen &amp; Larder" viewBox="0 0 10 10"></svg>',
  );

  render(<PlayConsole mapId="m1" renderUrl="/x/render?view=player" />);

  await waitFor(() => expect(seen.focusTarget).toBe("room.Kitchen & Larder"));
});

test("passes null focusTarget when the campaign SVG has no party node", async () => {
  const fetchSvg = vi
    .spyOn(api, "fetchRenderSvg")
    .mockResolvedValue('<svg viewBox="0 0 10 10"></svg>');

  render(<PlayConsole mapId="m1" renderUrl="/x/render?view=player" />);

  await waitFor(() => expect(fetchSvg).toHaveBeenCalled());
  await waitFor(() => expect(seen.focusTarget).toBeNull());
});
