# DungML header: current-user display + log in / log out

**Date:** 2026-07-03
**Status:** Approved — inline presentation + login button confirmed by user

## Problem

The dungml header (`AppHeader` in `packages/web/src/components/Layout.tsx`) already
renders `user.email` + a "Sign out" button when a session is live — but in the
running Keycloak deployment it shows a blank name. Two root causes:

1. **No display name is captured.** The backend
   (`KeycloakJWTIdentityProvider.authenticate`) extracts only `sub`, `email`, and
   roles. The OIDC client requests scope `"openid profile"` (no `email` scope), so
   Keycloak's access token carries `preferred_username`/`name` but **not** `email`.
   Result: `principal.email == ""` → the header shows nothing next to "Sign out".
2. **No logged-out affordance.** When there is no session the header renders
   nothing — there is no "Log in" control (it only matters on public pages such as
   `/docs`; protected pages redirect to `/login`).

Goal: show the current user in the header (like ttrpg3 does), with a visible
log-out control, and a log-in control when no session is live.

## Reference: how ttrpg3 does it

- Backend `Identity` carries `username` (`preferred_username`), `name`, `email`;
  `/me` returns a derived `display = name || username || subject`.
- Frontend `UserMenu` = initials **avatar + display name + a Radix dropdown**
  (Account / House Rules / chime / Log out).

dungml has `lucide-react` but **not** `@radix-ui/react-dropdown-menu`, and has no
avatar/profile/account-settings surface — so a faithful dropdown would hold only
"Log out". We therefore adopt ttrpg3's *identity model* (display-name derivation)
but a lighter *presentation* (see Decision).

## Decision: presentation

**Inline** (recommended): avatar chip (initials) + display name + a visible
**Sign out** button when logged in; a **Log in** button when logged out. No new
dependency.

Rejected alternative — **Dropdown** (exact ttrpg3 look): avatar + name trigger
opening a Radix menu whose only item is "Log out". Adds
`@radix-ui/react-dropdown-menu` for a one-item menu. The header presentation is
the only piece that differs between these; it is a small, swappable component, so
switching later is cheap.

## Design

### Backend

`packages/backend/src/dungml_backend/identity.py`
- Add `username: str = ""` and `name: str = ""` to `Principal`.
- `KeycloakJWTIdentityProvider.authenticate`: also read
  `claims.get("preferred_username", "")` → `username` and `claims.get("name", "")`
  → `name`.
- `StaticIdentityProvider`: give the dev principals a `username`/`name`
  (e.g. `username="dev-user"`, `name="Dev User"`) so dev mode shows a name too.

`packages/backend/src/dungml_backend/routes/auth.py`
- `/auth/me` returns `subject`, `email`, `username`, `name`, `roles`,
  `is_service`, and a server-derived
  `display = name or username or email or subject`.

**No DB migration.** The display name is read live from the token on each `/me`
call; we do not persist it. `models.User` and JIT-create stay as-is (still keyed
on `subject`).

### Frontend

`packages/web/src/lib/types.ts`
- Align the identity type with what `/me` actually returns (today `User` claims an
  `id` the endpoint never sends). Define:
  ```ts
  export interface User {
    subject: string;
    email: string;
    username: string;
    display: string;
    roles: string[];
    is_service: boolean;
  }
  ```

`packages/web/src/components/Layout.tsx` (`AppHeader`)
- Logged in: render `<Avatar initials>` + `user.display` + a **Sign out** button
  (existing `logout()` → navigate `/login`).
- Logged out (`ready && !token`): render a **Log in** button calling
  `login()` from `useAuth` (Keycloak redirect; in dev mode `login()` is a no-op,
  so guard on `mode === "keycloak"` or fall back to linking `/login`).
- Add a tiny local **Avatar** component: a circular chip showing up to two
  initials derived from `display` (no image/profile system).

`packages/web/src/components/Layout.module.css`
- Style the avatar chip; reuse existing `--fg-muted`, `--accent`, `--radius-*`
  tokens. Keep `.userBlock` layout.

No change needed to `AuthProvider` wiring — it already calls `apiAuth.me()` and
publishes `user`; it just gets a richer object.

## Data flow

Keycloak JWT → `KeycloakJWTIdentityProvider` → `Principal{subject, email,
username, name, roles}` → `/auth/me` derives `display` → `apiAuth.me()` →
`AuthProvider.user` → `AppHeader` renders avatar + `display` + Sign out.

## Error handling / edge cases

- `/me` fails or token absent → `user` is null → header shows the **Log in**
  affordance (keycloak) / nothing (dev, since you land on the dev sign-in).
- Empty `name` and `username` (unlikely) → `display` falls back to `email`, then
  `subject`; avatar initials fall back to `?`.
- Dev mode: static principals now carry a name, so the header shows "Dev User".

## Testing

- Backend: extend identity/auth tests to assert `username`/`name` extraction from
  claims and the `display` fallback chain in `/auth/me`
  (`tests/test_identity.py`, `tests/test_auth_routes.py`).
- Frontend: `Layout`/header test — renders `display` + Sign out when `user` set;
  renders Log in when logged out; avatar initials derivation
  (mirror `auth.test.ts` style).

## Out of scope (YAGNI)

- Persisted user profiles, editable display names, uploaded avatars,
  account-settings page — dungml has none of these and this feature does not need
  them.
- The `email` OIDC scope: not required, since `display` derives from
  `name`/`username`; add later only if email must always be shown.
