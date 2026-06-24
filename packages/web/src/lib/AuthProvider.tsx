// Auth context: wraps the OIDC useAuth hook and publishes its values on a
// React context so all pages can consume auth state via a single import.
//
// The OIDC hook (./useAuth) owns token acquisition and storage.
// This provider wires the live token into the api client via configureApi,
// and optionally fetches the display name from /api/auth/me once a token
// is present.
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useAuth as useOidcAuth } from "./useAuth";
import { configureApi, auth as apiAuth } from "./api";
import type { User } from "./types";

interface AuthState {
  token: string | null;
  ready: boolean;
  mode: "dev" | "keycloak";
  user: User | null;
  login: () => void;
  register: () => void;
  logout: () => void;
  // Kept for future Task-4 consumers; no-op until Task 4 wires the dev-token
  // form (LoginPage/RegisterPage will be rewritten to call login() / register()
  // without arguments).
  loading: boolean;
}

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const oidc = useOidcAuth();
  const [user, setUser] = useState<User | null>(null);

  // Wire the OIDC token into the api client so every fetch carries Bearer.
  useEffect(() => {
    configureApi({ getToken: () => oidc.token });
  }, [oidc.token]);

  // Best-effort: load the display name from /api/auth/me when a token arrives.
  useEffect(() => {
    if (!oidc.token) {
      setUser(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const me = await apiAuth.me();
        if (!cancelled) setUser(me);
      } catch {
        // Non-fatal: token is valid for API calls even without a display name.
        if (!cancelled) setUser(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [oidc.token]);

  const value = useMemo<AuthState>(
    () => ({
      token: oidc.token,
      ready: oidc.ready,
      mode: oidc.mode,
      user,
      login: oidc.login,
      register: oidc.register,
      logout: oidc.logout,
      // `loading` mirrors `!ready` so legacy consumers (ProtectedRoute etc.)
      // keep compiling until Task 4 migrates them to `ready`.
      loading: !oidc.ready,
    }),
    [oidc.token, oidc.ready, oidc.mode, oidc.login, oidc.register, oidc.logout, user],
  );

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(AuthCtx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}
