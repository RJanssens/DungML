import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";

afterEach(() => vi.unstubAllGlobals());

function jsonOnce(body: unknown, status = 200) {
  const mock = vi.fn(
    async () =>
      new Response(status === 204 ? null : JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("projects.members", () => {
  it("lists a project's members", async () => {
    api.configureApi({ getToken: () => "t" });
    const fetchMock = jsonOnce([
      { user_id: "u1", subject: "dev-user", email: "dev-user@dungml.local" },
    ]);

    const out = await api.projects.members.list("p1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/p1/members",
      expect.objectContaining({ method: "GET" }),
    );
    expect(out[0].subject).toBe("dev-user");
  });

  it("adds a member by identifier", async () => {
    api.configureApi({ getToken: () => "t" });
    const fetchMock = jsonOnce({ user_id: "u1", subject: "dev-user", email: "" }, 201);

    await api.projects.members.add("p1", "dev-user");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/p1/members",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ identifier: "dev-user" }),
      }),
    );
  });

  it("removes a member", async () => {
    api.configureApi({ getToken: () => "t" });
    const fetchMock = jsonOnce(null, 204);

    await api.projects.members.remove("p1", "u1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/p1/members/u1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});

describe("projects.campaigns", () => {
  it("reads the external campaigns playing on a project", async () => {
    api.configureApi({ getToken: () => "t" });
    const fetchMock = jsonOnce([
      {
        external_id: "return-to-stonehell",
        active_map_id: "m1",
        active_map_name: "Gatehouse",
        session_id: "s1",
        party_location: "room.stairs",
        discovered_nodes: 4,
        discovered_doors: 3,
        updated_at: "2026-09-22T10:00:00",
      },
    ]);

    const out = await api.projects.campaigns("p1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/p1/campaigns",
      expect.objectContaining({ method: "GET" }),
    );
    expect(out[0].active_map_name).toBe("Gatehouse");
    expect(out[0].party_location).toBe("room.stairs");
  });
});
