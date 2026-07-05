import { render, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { PlayConsole } from "./PlayConsole";
import * as api from "../lib/api";

afterEach(() => vi.restoreAllMocks());

test("campaign mode polls renderUrl and shows the SVG, no session calls", async () => {
  const fetchSvg = vi
    .spyOn(api, "fetchRenderSvg")
    .mockResolvedValue("<svg><g id='x'/></svg>");
  const sessGet = vi.spyOn(api.sessions, "get");

  const { container } = render(
    <PlayConsole mapId="m1" renderUrl="/instances/7/map/render?view=player" playerView />,
  );

  await waitFor(() =>
    expect(fetchSvg).toHaveBeenCalledWith("/instances/7/map/render?view=player"),
  );
  await waitFor(() =>
    expect(container.querySelector("svg")).not.toBeNull(),
  );

  expect(sessGet).not.toHaveBeenCalled();
});
