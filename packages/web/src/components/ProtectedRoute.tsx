import { Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "../lib/AuthProvider";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { token, ready } = useAuth();
  const location = useLocation();

  if (!ready) {
    return (
      <div style={{ padding: 40, color: "var(--fg-muted)" }}>Loading…</div>
    );
  }
  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}
