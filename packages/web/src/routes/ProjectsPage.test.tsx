import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import * as api from "../lib/api";
import type { Project } from "../lib/types";

// The app chrome reads the signed-in user through useAuth; these tests are
// about the project list, not the header (same as PlayPage.test.tsx).
vi.mock("../components/Layout", () => ({
  AppHeader: () => <div />,
  PageShell: (p: { children?: React.ReactNode }) => <div>{p.children}</div>,
  PageBody: (p: { children?: React.ReactNode }) => <div>{p.children}</div>,
}));

import { ProjectsPage } from "./ProjectsPage";

afterEach(() => vi.restoreAllMocks());

const base = { created_at: "2026-09-26T12:00:00Z", updated_at: "2026-09-26T12:00:00Z", owner: "gm@x" };
const P = (id: string, role: Project["role"], is_public = true): Project => ({
  ...base, id, name: id, role, is_public, shared: role !== "owner",
});

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><ProjectsPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

test("projects are grouped by how you reach them", async () => {
  vi.spyOn(api.projects, "list").mockResolvedValue([
    P("mine", "owner", false), P("shared-in", "member"), P("everyone", "public"),
  ]);
  mount();
  const mine = await screen.findByRole("region", { name: /mine/i });
  expect(within(mine).getByText("mine")).toBeInTheDocument();
  expect(within(mine).getByText(/private/i)).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: /shared with me/i })).getByText("shared-in")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: /^public$/i })).getByText("everyone")).toBeInTheDocument();
});

test("empty groups are not shown", async () => {
  vi.spyOn(api.projects, "list").mockResolvedValue([P("mine", "owner")]);
  mount();
  await screen.findByRole("region", { name: /mine/i });
  expect(screen.queryByRole("region", { name: /shared with me/i })).toBeNull();
  expect(screen.queryByRole("region", { name: /^public$/i })).toBeNull();
});

test("a public project shows no Delete button", async () => {
  vi.spyOn(api.projects, "list").mockResolvedValue([P("everyone", "public")]);
  mount();
  const pub = await screen.findByRole("region", { name: /^public$/i });
  expect(within(pub).queryByRole("button", { name: /delete/i })).toBeNull();
});
