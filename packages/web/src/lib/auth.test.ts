import { describe, expect, it } from "vitest";

import { authMode, DevTokenStore, oidcSettings } from "./auth";

describe("dungml web auth helpers", () => {
  it("authMode defaults to dev, opts into keycloak", () => {
    expect(authMode({})).toBe("dev");
    expect(authMode({ VITE_AUTH_MODE: "keycloak" })).toBe("keycloak");
  });

  it("oidcSettings builds the realm authority + dungml-web client", () => {
    const cfg = oidcSettings({
      VITE_KEYCLOAK_URL: "http://kc:8080",
      VITE_KEYCLOAK_REALM: "dungeon-daemon",
      VITE_APP_ORIGIN: "http://localhost:5174",
    });
    expect(cfg.authority).toBe("http://kc:8080/realms/dungeon-daemon");
    expect(cfg.client_id).toBe("dungml-web");
    expect(cfg.redirect_uri).toBe("http://localhost:5174/");
  });

  it("DevTokenStore reads/writes with a dev-user fallback", () => {
    const mem = new Map<string, string>();
    const storage = {
      getItem: (k: string) => mem.get(k) ?? null,
      setItem: (k: string, v: string) => void mem.set(k, v),
      removeItem: (k: string) => void mem.delete(k),
    };
    const store = new DevTokenStore(storage);
    expect(store.get()).toBe("dev-user");
    store.set("dev-service");
    expect(store.get()).toBe("dev-service");
  });
});
