# Header Current-User Display + Login/Logout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the current user (initials avatar + display name) in the dungml header with a visible Sign out button, and a Log in button when no session is live.

**Architecture:** The Keycloak JWT already carries `preferred_username`/`name`; the backend just doesn't surface them. We add those fields to `Principal`, extract claim-parsing into a pure testable helper, and have `/auth/me` return a derived `display` name. The frontend fixes its `User` type to match `/me`, adds a pure `initials()` helper, and renders an inline avatar + name + Sign out / Log in in `AppHeader`.

**Tech Stack:** FastAPI + PyJWT (backend), React + react-router + CSS modules + vitest (frontend). Design ref: `docs/superpowers/specs/2026-07-03-header-current-user-design.md`.

## Global Constraints

- Python `>=3.12`; backend tests run from repo root via `uv run pytest <path>`.
- **No new dependencies** — backend or frontend. Inline presentation only (no Radix dropdown). Reuse the existing `Button` primitive and CSS custom-properties (`--accent`, `--fg`, `--fg-muted`, `--bg-elevated`, `--radius-sm`).
- **No DB migration** — display name is read live from the token per `/me` call; `models.User` and JIT-create are unchanged.
- The Keycloak JWT provider is not unit-tested directly (signed-JWT + JWKS mocking is out of scope); test the pure claim-parsing helper instead.
- The frontend has vitest but **no jsdom/testing-library** — logic lives in pure, node-testable helpers; React wiring is verified by `tsc`/`vite build`.
- TDD, frequent commits, DRY, YAGNI.

---

### Task 1: Backend — capture `username`/`name` in `Principal` via a pure claims helper

**Files:**
- Modify: `packages/backend/src/dungml_backend/identity.py`
- Test: `packages/backend/tests/test_identity.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `Principal(subject, email="", roles=(), is_service=False, username="", name="")` (frozen dataclass; two new trailing fields).
  - `principal_from_claims(claims: dict, service_client_id: str) -> Principal` — pure; raises `IdentityError` when `sub` is missing.
  - `display_name(p: Principal) -> str` — returns `p.name or p.username or p.email or p.subject`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/backend/tests/test_identity.py`:

```python
from dungml_backend.identity import display_name, principal_from_claims


def test_principal_from_claims_extracts_profile_fields():
    claims = {
        "sub": "kc-123",
        "email": "raf@example.org",
        "preferred_username": "raf",
        "name": "Raf Janssens",
        "realm_access": {"roles": ["dm"]},
        "azp": "dungml-web",
    }
    p = principal_from_claims(claims, service_client_id="dungeon-daemon-service")
    assert p.subject == "kc-123"
    assert p.username == "raf"
    assert p.name == "Raf Janssens"
    assert p.email == "raf@example.org"
    assert p.roles == ("dm",)
    assert p.is_service is False


def test_principal_from_claims_flags_service_by_azp():
    p = principal_from_claims(
        {"sub": "svc", "azp": "dungeon-daemon-service"},
        service_client_id="dungeon-daemon-service",
    )
    assert p.is_service is True


def test_principal_from_claims_requires_subject():
    with pytest.raises(IdentityError):
        principal_from_claims({"preferred_username": "x"}, service_client_id="svc")


def test_display_name_fallback_chain():
    assert display_name(Principal("s", "e@x", (), False, "uname", "Full Name")) == "Full Name"
    assert display_name(Principal("s", "e@x", (), False, "uname", "")) == "uname"
    assert display_name(Principal("s", "e@x", (), False, "", "")) == "e@x"
    assert display_name(Principal("s", "", (), False, "", "")) == "s"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/backend/tests/test_identity.py -q`
Expected: FAIL — `ImportError: cannot import name 'display_name'` / `principal_from_claims`.

- [ ] **Step 3: Implement in `identity.py`**

Add the two new fields to `Principal`:

```python
@dataclass(frozen=True)
class Principal:
    subject: str
    email: str = ""
    roles: tuple[str, ...] = ()
    is_service: bool = False
    username: str = ""
    name: str = ""
```

Add module-level helpers (place after `IdentityError`, before the `IdentityProvider` Protocol):

```python
def principal_from_claims(claims: dict, service_client_id: str) -> Principal:
    """Map OIDC/JWT claims to a Principal. Pure — no network, no token decode."""
    subject = claims.get("sub")
    if not subject:
        raise IdentityError("token has no subject")
    return Principal(
        subject=subject,
        email=claims.get("email", ""),
        roles=tuple(claims.get("realm_access", {}).get("roles", [])),
        is_service=claims.get("azp") == service_client_id,
        username=claims.get("preferred_username", ""),
        name=claims.get("name", ""),
    )


def display_name(p: Principal) -> str:
    """Best human-readable label for a principal, with graceful fallbacks."""
    return p.name or p.username or p.email or p.subject
```

Rewrite `KeycloakJWTIdentityProvider.authenticate` to reuse the helper (replace the manual `Principal(...)` construction at the end):

```python
    def authenticate(self, token: str) -> Principal:
        import jwt

        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, signing_key.key, algorithms=["RS256"],
                audience=self._audience, issuer=self._issuer,
                options={"verify_aud": self._audience is not None},
            )
        except Exception as exc:
            raise IdentityError(str(exc)) from exc
        return principal_from_claims(claims, self._service_client_id)
```

Give the dev principal a name in `StaticIdentityProvider.__init__` (the `dev_token` entry):

```python
            config.settings.dev_token: Principal(
                "dev-user", "dev-user@dungml.local", ("dm",), False,
                username="dev-user", name="Dev User",
            ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/backend/tests/test_identity.py -q`
Expected: PASS (all identity tests, old + new).

- [ ] **Step 5: Commit**

```bash
cd /home/raf/roleplaying/dungml
git add packages/backend/src/dungml_backend/identity.py packages/backend/tests/test_identity.py
git commit -m "feat(backend): capture username/name in Principal + display_name helper

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Backend — `/auth/me` returns `username`, `name`, `display`

**Files:**
- Modify: `packages/backend/src/dungml_backend/routes/auth.py`
- Test: `packages/backend/tests/test_auth_routes.py`

**Interfaces:**
- Consumes: `display_name` from Task 1; `CurrentPrincipal` dependency (unchanged).
- Produces: `GET /api/auth/me` JSON `{subject, email, username, name, display, roles, is_service}`.

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_auth_routes.py`:

```python
def test_me_returns_display_name(client):
    client.headers["Authorization"] = "Bearer dev-user"
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "dev-user"
    assert body["display"] == "Dev User"  # name wins the fallback chain
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/backend/tests/test_auth_routes.py::test_me_returns_display_name -q`
Expected: FAIL — `KeyError`/assert on `body["username"]` (field not present yet).

- [ ] **Step 3: Implement in `routes/auth.py`**

```python
from ..deps import CurrentPrincipal
from ..identity import display_name

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
def me(principal: CurrentPrincipal) -> dict:
    return {
        "subject": principal.subject,
        "email": principal.email,
        "username": principal.username,
        "name": principal.name,
        "display": display_name(principal),
        "roles": list(principal.roles),
        "is_service": principal.is_service,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/raf/roleplaying/dungml && uv run pytest packages/backend/tests/test_auth_routes.py -q`
Expected: PASS (both the existing `/me` test and the new one).

- [ ] **Step 5: Commit**

```bash
cd /home/raf/roleplaying/dungml
git add packages/backend/src/dungml_backend/routes/auth.py packages/backend/tests/test_auth_routes.py
git commit -m "feat(backend): /auth/me returns username/name/display

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Frontend — pure `initials()` helper

**Files:**
- Create: `packages/web/src/lib/avatar.ts`
- Test: `packages/web/src/lib/avatar.test.ts`

**Interfaces:**
- Produces: `initials(name: string): string` — up to two uppercase letters for the avatar chip.

- [ ] **Step 1: Write the failing test**

Create `packages/web/src/lib/avatar.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { initials } from "./avatar";

describe("initials", () => {
  it("takes first letters of the first two words", () => {
    expect(initials("Raf Janssens")).toBe("RJ");
    expect(initials("  ada  lovelace  king ")).toBe("AL");
  });

  it("uses first two chars of a single token", () => {
    expect(initials("raf")).toBe("RA");
    expect(initials("dev-user")).toBe("DE");
  });

  it("falls back to ? for empty input", () => {
    expect(initials("")).toBe("?");
    expect(initials("   ")).toBe("?");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/raf/roleplaying/dungml/packages/web && npx vitest run src/lib/avatar.test.ts`
Expected: FAIL — cannot resolve `./avatar`.

- [ ] **Step 3: Create `avatar.ts`**

```ts
// Two-letter initials for the header avatar chip. Splits on whitespace and
// takes the first letter of the first two words; for a single token, the first
// two characters; "?" when there is nothing usable.
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/raf/roleplaying/dungml/packages/web && npx vitest run src/lib/avatar.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/raf/roleplaying/dungml
git add packages/web/src/lib/avatar.ts packages/web/src/lib/avatar.test.ts
git commit -m "feat(web): initials() helper for header avatar

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Frontend — `User` type + inline avatar/name + Sign out / Log in in `AppHeader`

**Files:**
- Modify: `packages/web/src/lib/types.ts` (the `User` interface, lines 3-6)
- Modify: `packages/web/src/components/Layout.tsx` (`AppHeader`, lines 7-36)
- Modify: `packages/web/src/components/Layout.module.css` (`.userEmail` block, lines 59-61)

**Interfaces:**
- Consumes: `initials` (Task 3); `/auth/me` shape (Task 2); `useAuth()` context which already exposes `{ user, token, ready, mode, login, logout }`.
- Produces: header UI. No new exports.

**Note on testing:** there is no jsdom/testing-library in this project, so this task has no component unit test — its logic (initials, display derivation) is unit-tested in Tasks 1-3. Verification is `tsc` typecheck + `vite build` (Step 4) plus the manual visual check (Step 5).

- [ ] **Step 1: Update the `User` type in `types.ts`**

Replace the `User` interface (currently `{ id: string; email: string }` — note `id` is sent by no endpoint and read by no code) with the `/me` shape:

```ts
export interface User {
  subject: string;
  email: string;
  username: string;
  name: string;
  display: string;
  roles: string[];
  is_service: boolean;
}
```

- [ ] **Step 2: Update `AppHeader` in `Layout.tsx`**

Add the import near the other lib imports:

```tsx
import { initials } from "../lib/avatar";
```

Replace the `AppHeader` function body (keep `Logo`, `PageShell`, `PageBody` unchanged):

```tsx
export function AppHeader({ right }: { right?: ReactNode }) {
  const { user, token, ready, mode, login, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <header className={styles.header}>
      <Link to="/" className={styles.brand}>
        <Logo />
        <span>dungml</span>
      </Link>
      <div className={styles.spacer}>{right}</div>
      <Link to="/docs" className={styles.docsLink} title="DSL reference">
        Docs
      </Link>
      {token && user ? (
        <div className={styles.userBlock}>
          <span className={styles.avatar} aria-hidden>
            {initials(user.display)}
          </span>
          <span className={styles.userName} title={user.email || user.display}>
            {user.display}
          </span>
          <Button
            variant="ghost"
            onClick={async () => {
              await logout();
              navigate("/login");
            }}
          >
            Sign out
          </Button>
        </div>
      ) : ready && mode === "keycloak" ? (
        <Button variant="ghost" onClick={() => login()}>
          Log in
        </Button>
      ) : null}
    </header>
  );
}
```

(In dev mode `login()` is a no-op and logged-out users land on the dev sign-in page, so the Log in button is intentionally gated to `mode === "keycloak"`.)

- [ ] **Step 3: Update `Layout.module.css`**

Replace the `.userEmail` rule (lines 59-61) with the avatar + name styles:

```css
.avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--accent);
  color: var(--bg-elevated);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  flex-shrink: 0;
}

.userName {
  max-width: 12rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--fg);
}
```

- [ ] **Step 4: Typecheck + build + run existing tests**

Run: `cd /home/raf/roleplaying/dungml/packages/web && npm run build && npm run test`
Expected: `tsc -b` and `vite build` succeed with no type errors; all vitest suites pass (including `auth.test.ts` and the new `avatar.test.ts`).

- [ ] **Step 5: Manual visual verification against the running app**

The app is served as a built SPA by `dmap-server`. Rebuild and verify in the browser:
- Logged in (keycloak session): header shows an initials chip + your display name + **Sign out**. Clicking Sign out redirects to Keycloak logout.
- Visit `/docs` while logged out (or after signout): header shows a **Log in** button that starts the Keycloak redirect.

Deploy note (from repo memory `deploy-service.md`): a frontend change needs `npm run build` then restart of the serving process for the built SPA to update.

- [ ] **Step 6: Commit**

```bash
cd /home/raf/roleplaying/dungml
git add packages/web/src/lib/types.ts packages/web/src/components/Layout.tsx packages/web/src/components/Layout.module.css
git commit -m "feat(web): header shows current user (avatar+name) with Sign out / Log in

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Backend surfaces a real display name (name/username, not just email) → Tasks 1-2. ✓
- `/auth/me` returns `display` → Task 2. ✓
- Frontend `User` type aligned to `/me` (drops phantom `id`) → Task 4 Step 1. ✓
- Inline avatar + display name + visible Sign out → Task 4. ✓
- Log in button when logged out (keycloak) → Task 4 Step 2. ✓
- No DB migration, no new deps → Global Constraints; honored throughout. ✓
- Tests for username/name extraction + display fallback → Task 1; `/me` display → Task 2. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The "no component test" in Task 4 is an explicit, justified decision (no jsdom infra), not a deferred placeholder — the underlying logic is tested in Tasks 1-3.

**Type consistency:** `principal_from_claims` / `display_name` signatures match between Task 1 (definition) and Task 2 (use). `Principal` field order `(subject, email, roles, is_service, username, name)` is consistent between the dataclass, the positional `display_name` test cases, and the `StaticIdentityProvider` construction. Frontend `User.display` (Task 4 type) matches `initials(user.display)` usage and the `/me` `display` field (Task 2). `useAuth()` fields consumed (`user, token, ready, mode, login, logout`) all exist on `AuthState` in `AuthProvider.tsx`.
