// Auth helpers, free of any oidc-client-ts import so they unit-test in node.
// Mode mirrors the dungml backend's DUNGML_AUTH_MODE: "dev" uses a manual bearer
// token (dev-user); "keycloak" runs the OIDC auth-code + PKCE flow against the
// shared dungeon-daemon realm.
export type AuthMode = "dev" | "keycloak";

type Env = Record<string, string | undefined>;

export function authMode(env: Env = import.meta.env): AuthMode {
  return env.VITE_AUTH_MODE === "keycloak" ? "keycloak" : "dev";
}

export interface OidcConfig {
  authority: string;
  client_id: string;
  redirect_uri: string;
  post_logout_redirect_uri: string;
  response_type: string;
  scope: string;
  automaticSilentRenew: boolean;
}

export function oidcSettings(env: Env = import.meta.env): OidcConfig {
  const kcUrl = env.VITE_KEYCLOAK_URL ?? "http://localhost:8080";
  const realm = env.VITE_KEYCLOAK_REALM ?? "dungeon-daemon";
  const origin =
    env.VITE_APP_ORIGIN ??
    (typeof window !== "undefined" ? window.location.origin : "");
  return {
    authority: `${kcUrl}/realms/${realm}`,
    client_id: env.VITE_KEYCLOAK_CLIENT_ID ?? "dungml-web",
    redirect_uri: `${origin}/`,
    post_logout_redirect_uri: `${origin}/`,
    response_type: "code",
    scope: "openid profile",
    automaticSilentRenew: true,
  };
}

interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export class DevTokenStore {
  constructor(
    private storage: StorageLike,
    private key = "dungml-token",
  ) {}

  get(): string {
    return this.storage.getItem(this.key) ?? "dev-user";
  }

  set(value: string): void {
    this.storage.setItem(this.key, value);
  }
}
