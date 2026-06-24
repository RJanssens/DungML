import { useEffect, useRef, useState } from "react";
import { UserManager, WebStorageStateStore } from "oidc-client-ts";

import { authMode, DevTokenStore, oidcSettings } from "./auth";

export interface Auth {
  mode: "dev" | "keycloak";
  token: string | null;
  ready: boolean;
  // True when a previously-signed-in session lapsed (access token expired and
  // silent renew failed), so the UI can say "session expired" rather than the
  // first-time "sign in" prompt.
  expired: boolean;
  login: () => void;
  register: () => void;
  logout: () => void;
  setDevToken: (t: string) => void;
}

function makeUserManager(): UserManager {
  return new UserManager({
    ...oidcSettings(),
    userStore: new WebStorageStateStore({ store: window.localStorage }),
  });
}

export function useAuth(): Auth {
  const mode = authMode();
  const store = useRef(new DevTokenStore(window.localStorage)).current;
  const mgr = useRef<UserManager | null>(null);

  const [devToken, setDevToken] = useState(() => store.get());
  const [kcToken, setKcToken] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [ready, setReady] = useState(mode === "dev");
  // StrictMode runs effects twice in dev; without this guard the OIDC callback
  // exchanges the same authorization code twice and Keycloak rejects the second
  // exchange with CODE_TO_TOKEN_ERROR / invalid_code. Set synchronously before
  // any await so the second pass bails out before it can POST the code again.
  const started = useRef(false);

  useEffect(() => {
    if (mode !== "keycloak") return;
    if (started.current) return;
    started.current = true;
    mgr.current ??= makeUserManager();
    const manager = mgr.current;
    // Keep React state in sync with the live token. oidc-client-ts silently
    // renews from the refresh token before expiry and emits addUserLoaded with
    // the fresh token; without picking that up here the app keeps sending the
    // first (short-lived) access token and every call 401s once it lapses.
    manager.events.addUserLoaded((user) => {
      setKcToken(user.access_token);
      setExpired(false);
    });
    manager.events.addUserUnloaded(() => setKcToken(null));
    // The access token lapsed and the background renew couldn't recover it:
    // drop the token and flag the session as expired (vs. never signed in).
    manager.events.addAccessTokenExpired(() => {
      setKcToken(null);
      setExpired(true);
    });
    manager.events.addSilentRenewError(() => {
      setKcToken(null);
      setExpired(true);
    });
    (async () => {
      try {
        if (window.location.search.includes("code=")) {
          const user = await manager.signinRedirectCallback();
          window.history.replaceState({}, "", "/");
          setKcToken(user.access_token);
        } else {
          const user = await manager.getUser();
          if (user && !user.expired) {
            setKcToken(user.access_token);
          } else if (user) {
            // Stored session whose access token lapsed while the tab was away:
            // renew from the refresh token instead of forcing a fresh login.
            try {
              const renewed = await manager.signinSilent();
              setKcToken(renewed?.access_token ?? null);
            } catch {
              setKcToken(null);
              setExpired(true);
            }
          } else {
            setKcToken(null);
          }
        }
      } catch {
        setKcToken(null);
      } finally {
        setReady(true);
      }
    })();
  }, [mode]);

  if (mode === "dev") {
    return {
      mode,
      token: devToken || null,
      ready: true,
      expired: false,
      login: () => {},
      register: () => {},
      logout: () => {
        store.set("");
        setDevToken("");
      },
      setDevToken: (t: string) => {
        store.set(t);
        setDevToken(t);
      },
    };
  }

  return {
    mode,
    token: kcToken,
    ready,
    expired,
    login: () => void (mgr.current ??= makeUserManager()).signinRedirect(),
    // Keycloak jumps straight to the registration form on prompt=create.
    register: () =>
      void (mgr.current ??= makeUserManager()).signinRedirect({
        extraQueryParams: { prompt: "create" },
      }),
    logout: () => {
      const manager = (mgr.current ??= makeUserManager());
      manager.signoutRedirect().catch(() => void manager.removeUser());
    },
    setDevToken: () => {},
  };
}
