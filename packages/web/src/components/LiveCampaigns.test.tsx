import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import * as api from "../lib/api";
import { LiveCampaigns } from "./LiveCampaigns";

afterEach(() => vi.restoreAllMocks());

function mount(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const LIVE = {
  external_id: "return-to-stonehell",
  active_map_id: "m1",
  active_map_name: "Gatehouse",
  session_id: "s1",
  party_location: "room.stairs",
  discovered_nodes: 4,
  discovered_doors: 3,
  total_nodes: 18,
  updated_at: "2026-09-22T10:00:00",
};

test("names the campaign, its map and where the party stands", async () => {
  vi.spyOn(api.projects, "campaigns").mockResolvedValue([LIVE]);
  mount(<LiveCampaigns projectId="p1" />);

  expect(await screen.findByText("return-to-stonehell")).toBeInTheDocument();
  expect(screen.getByText(/Gatehouse/)).toBeInTheDocument();
  expect(screen.getByText(/room.stairs/)).toBeInTheDocument();
});

test("reads the party's progress as a fraction of the map", async () => {
  vi.spyOn(api.projects, "campaigns").mockResolvedValue([LIVE]);
  mount(<LiveCampaigns projectId="p1" />);
  expect(await screen.findByText(/4 \/ 18 areas/)).toBeInTheDocument();
});

test("links into the campaign's own play session", async () => {
  vi.spyOn(api.projects, "campaigns").mockResolvedValue([LIVE]);
  mount(<LiveCampaigns projectId="p1" />);

  const link = await screen.findByRole("link", { name: /open/i });
  expect(link).toHaveAttribute("href", "/maps/m1/play?session=s1");
});

test("renders nothing when no campaign is linked", async () => {
  const spy = vi.spyOn(api.projects, "campaigns").mockResolvedValue([]);
  const { container } = mount(<LiveCampaigns projectId="p1" />);
  await vi.waitFor(() => expect(spy).toHaveBeenCalled());
  expect(container.textContent).toBe("");
});

test("says so when a linked campaign has not chosen a map yet", async () => {
  vi.spyOn(api.projects, "campaigns").mockResolvedValue([
    { ...LIVE, active_map_id: null, active_map_name: null, session_id: null, party_location: null },
  ]);
  mount(<LiveCampaigns projectId="p1" />);

  expect(await screen.findByText(/no map in play/i)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /open/i })).toBeNull();
});
