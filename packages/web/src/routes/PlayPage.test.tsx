import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, test, vi } from "vitest";

// Capture what PlayPage hands the console — the point of the ?session= param
// is that a link can open one specific session without the picker.
const seen: { mapId?: string; sessionId?: string } = {};
vi.mock("../components/PlayConsole", () => ({
  PlayConsole: (p: { mapId: string; sessionId?: string }) => {
    seen.mapId = p.mapId;
    seen.sessionId = p.sessionId;
    return <div data-testid="play-console" />;
  },
}));

// The app chrome reads the signed-in user through useAuth; this test is
// about the query-string plumbing, not the header.
vi.mock("../components/Layout", () => ({
  AppHeader: () => <div />,
  PageShell: (p: { children?: React.ReactNode }) => <div>{p.children}</div>,
  PageBody: (p: { children?: React.ReactNode }) => <div>{p.children}</div>,
}));

import { PlayPage } from "./PlayPage";

function mountAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/maps/:mapId/play" element={<PlayPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

test("pins the console to the session named in the query string", () => {
  mountAt("/maps/m1/play?session=s1");
  expect(seen.mapId).toBe("m1");
  expect(seen.sessionId).toBe("s1");
});

test("leaves the session unpinned when the query string omits it", () => {
  mountAt("/maps/m1/play");
  expect(seen.sessionId).toBeUndefined();
});
