import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import * as api from "../lib/api";
import { ProjectMembers } from "./ProjectMembers";

afterEach(() => vi.restoreAllMocks());

function mount(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

test("lists the project's members", async () => {
  vi.spyOn(api.projects.members, "list").mockResolvedValue([
    { user_id: "u1", subject: "dev-user", email: "dev-user@dungml.local" },
  ]);
  mount(<ProjectMembers projectId="p1" isPublic isOwner owner="me@example.com" />);
  expect(await screen.findByText("dev-user@dungml.local")).toBeInTheDocument();
});

test("shows the owner alongside the members", async () => {
  vi.spyOn(api.projects.members, "list").mockResolvedValue([]);
  mount(<ProjectMembers projectId="p1" isPublic isOwner owner="me@example.com" />);
  expect(await screen.findByText(/me@example.com/)).toBeInTheDocument();
});

test("adds a member by identifier", async () => {
  vi.spyOn(api.projects.members, "list").mockResolvedValue([]);
  const add = vi
    .spyOn(api.projects.members, "add")
    .mockResolvedValue({ user_id: "u1", subject: "dev-user", email: "" });

  mount(<ProjectMembers projectId="p1" isPublic isOwner owner="me@example.com" />);
  const input = await screen.findByPlaceholderText(/email or subject/i);
  fireEvent.change(input, { target: { value: "dev-user" } });
  fireEvent.click(screen.getByRole("button", { name: /share/i }));

  await waitFor(() => expect(add).toHaveBeenCalledWith("p1", "dev-user"));
});

test("reports a user who has never signed in", async () => {
  vi.spyOn(api.projects.members, "list").mockResolvedValue([]);
  vi.spyOn(api.projects.members, "add").mockRejectedValue(
    new api.ApiError(404, null, "no user matching 'ghost'"),
  );

  mount(<ProjectMembers projectId="p1" isPublic isOwner owner="me@example.com" />);
  fireEvent.change(await screen.findByPlaceholderText(/email or subject/i), {
    target: { value: "ghost" },
  });
  fireEvent.click(screen.getByRole("button", { name: /share/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/no user matching/i);
});

test("hides the sharing controls from a member", async () => {
  vi.spyOn(api.projects.members, "list").mockResolvedValue([
    { user_id: "u1", subject: "dev-user", email: "dev-user@dungml.local" },
  ]);
  mount(<ProjectMembers projectId="p1" isPublic isOwner={false} owner="me@example.com" />);

  expect(await screen.findByText("dev-user@dungml.local")).toBeInTheDocument();
  expect(screen.queryByPlaceholderText(/email or subject/i)).toBeNull();
  expect(screen.queryByRole("button", { name: /remove/i })).toBeNull();
});

test("labels the campaign daemon so the GM knows what it is", async () => {
  vi.spyOn(api.projects.members, "list").mockResolvedValue([
    {
      user_id: "u2",
      subject: "@dungeon-daemon-service",
      email: "service@dungml.local",
    },
  ]);
  mount(<ProjectMembers projectId="p1" isPublic isOwner owner="me@example.com" />);

  expect(await screen.findByText(/campaign service/i)).toBeInTheDocument();
});

test("the owner can make a public project private", async () => {
  vi.spyOn(api.projects.members, "list").mockResolvedValue([]);
  const setPublic = vi
    .spyOn(api.projects, "setPublic")
    .mockResolvedValue({} as never);
  mount(<ProjectMembers projectId="p1" isPublic isOwner owner="me@example.com" />);
  const toggle = await screen.findByRole("checkbox", { name: /public/i });
  expect(toggle).toBeChecked();
  fireEvent.click(toggle);
  await waitFor(() => expect(setPublic).toHaveBeenCalledWith("p1", false));
});

test("a non-owner sees the visibility but cannot change it", async () => {
  vi.spyOn(api.projects.members, "list").mockResolvedValue([]);
  mount(<ProjectMembers projectId="p1" isPublic isOwner={false} owner="me@example.com" />);
  expect(await screen.findByText(/public — everyone who signs in/i)).toBeInTheDocument();
  expect(screen.queryByRole("checkbox", { name: /public/i })).toBeNull();
});
