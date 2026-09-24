import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import * as api from "../lib/api";
import { ProjectSessions } from "./ProjectSessions";

afterEach(() => vi.restoreAllMocks());

function mount(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const GM_SESSION = {
  session_id: "s2",
  name: "Tuesday group",
  map_id: "m2",
  map_name: "Level 1A",
  party_location: "room.room_3",
  discovered_nodes: 5,
  total_nodes: 20,
  external_id: null,
  updated_at: "2026-09-20T10:00:00",
};

const DRIVEN_SESSION = {
  session_id: "s1",
  name: "ttrpg2 · return-to-stonehell",
  map_id: "m1",
  map_name: "Surface Level Gatehouse",
  party_location: "room.room_9",
  discovered_nodes: 10,
  total_nodes: 18,
  external_id: "return-to-stonehell",
  updated_at: "2026-09-22T15:00:00",
};

test("shows each session's map and progress", async () => {
  vi.spyOn(api.projects, "sessions").mockResolvedValue([DRIVEN_SESSION, GM_SESSION]);
  mount(<ProjectSessions projectId="p1" />);

  expect(await screen.findByText(/Surface Level Gatehouse/)).toBeInTheDocument();
  expect(screen.getByText(/10 \/ 18 areas/)).toBeInTheDocument();
  expect(screen.getByText(/5 \/ 20 areas/)).toBeInTheDocument();
});

test("links each row into its own session", async () => {
  vi.spyOn(api.projects, "sessions").mockResolvedValue([DRIVEN_SESSION]);
  mount(<ProjectSessions projectId="p1" />);

  const link = await screen.findByRole("link", {
    name: /ttrpg2 · return-to-stonehell/,
  });
  expect(link).toHaveAttribute("href", "/maps/m1/play?session=s1");
});

test("marks the sessions an external campaign drives", async () => {
  vi.spyOn(api.projects, "sessions").mockResolvedValue([DRIVEN_SESSION, GM_SESSION]);
  const { container } = mount(<ProjectSessions projectId="p1" />);
  await screen.findByText(/Surface Level Gatehouse/);

  const live = container.querySelectorAll("[data-driven='true']");
  expect(live).toHaveLength(1);
});

test("says where the party stands", async () => {
  vi.spyOn(api.projects, "sessions").mockResolvedValue([DRIVEN_SESSION]);
  mount(<ProjectSessions projectId="p1" />);
  expect(await screen.findByText(/room.room_9/)).toBeInTheDocument();
});

test("renders nothing when the project has no sessions", async () => {
  const spy = vi.spyOn(api.projects, "sessions").mockResolvedValue([]);
  const { container } = mount(<ProjectSessions projectId="p1" />);
  await vi.waitFor(() => expect(spy).toHaveBeenCalled());
  expect(container.textContent).toBe("");
});


test("deletes a session after confirming", async () => {
  vi.spyOn(api.projects, "sessions").mockResolvedValue([GM_SESSION]);
  const remove = vi.spyOn(api.sessions, "remove").mockResolvedValue(undefined);
  vi.stubGlobal("confirm", vi.fn(() => true));

  mount(<ProjectSessions projectId="p1" />);
  fireEvent.click(await screen.findByRole("button", { name: /delete session/i }));

  await waitFor(() => expect(remove).toHaveBeenCalledWith("s2"));
});

test("keeps the session when the confirmation is declined", async () => {
  vi.spyOn(api.projects, "sessions").mockResolvedValue([GM_SESSION]);
  const remove = vi.spyOn(api.sessions, "remove").mockResolvedValue(undefined);
  vi.stubGlobal("confirm", vi.fn(() => false));

  mount(<ProjectSessions projectId="p1" />);
  fireEvent.click(await screen.findByRole("button", { name: /delete session/i }));

  expect(remove).not.toHaveBeenCalled();
});

test("warns that a campaign will lose its fog", async () => {
  vi.spyOn(api.projects, "sessions").mockResolvedValue([DRIVEN_SESSION]);
  vi.spyOn(api.sessions, "remove").mockResolvedValue(undefined);
  const ask = vi.fn((_message?: string) => false);
  vi.stubGlobal("confirm", ask);

  mount(<ProjectSessions projectId="p1" />);
  fireEvent.click(await screen.findByRole("button", { name: /delete session/i }));

  expect(String(ask.mock.calls[0][0])).toMatch(/return-to-stonehell/);
});
