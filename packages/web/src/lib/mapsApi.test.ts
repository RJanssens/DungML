import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("maps.setDefault", () => {
  it("PUTs the project-scoped default route and returns the summary", async () => {
    api.configureApi({ getToken: () => "t" });
    const body = {
      id: "m1",
      project_id: "p1",
      name: "M",
      kind: "map",
      is_default: true,
      created_at: "",
      updated_at: "",
    };
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const out = await api.maps.setDefault("p1", "m1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/p1/maps/m1/default",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(out.is_default).toBe(true);
  });
});
