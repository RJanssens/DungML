import {
  createBrowserRouter,
  createRoutesFromElements,
  Route,
} from "react-router-dom";
import { LoginPage } from "./routes/LoginPage";
import { RegisterPage } from "./routes/RegisterPage";
import { ProjectsPage } from "./routes/ProjectsPage";
import { ProjectPage } from "./routes/ProjectPage";
import { MapEditorPage } from "./routes/MapEditorPage";
import { MapPrintPage } from "./routes/MapPrintPage";
import { PlayPage } from "./routes/PlayPage";
import { DocsPage } from "./routes/DocsPage";
import { ProtectedRoute } from "./components/ProtectedRoute";

// A data router (createBrowserRouter) rather than <BrowserRouter>/<Routes> so
// the data-router-only navigation APIs are available — notably useBlocker,
// which the map editor uses to confirm before discarding unsaved changes.
export const router = createBrowserRouter(
  createRoutesFromElements(
    <>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/docs" element={<DocsPage />} />
      <Route path="/docs/:docId" element={<DocsPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <ProjectsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/projects/:projectId"
        element={
          <ProtectedRoute>
            <ProjectPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/maps/:mapId"
        element={
          <ProtectedRoute>
            <MapEditorPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/maps/:mapId/print"
        element={
          <ProtectedRoute>
            <MapPrintPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/maps/:mapId/play"
        element={
          <ProtectedRoute>
            <PlayPage />
          </ProtectedRoute>
        }
      />
    </>,
  ),
);
