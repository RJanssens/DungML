# dungml over TLS (system-wide)

**Date:** 2026-07-03
**Status:** Approved (scope: full system; cert: reuse shared cert)

## Problem

dungml serves its SPA and API over plain **HTTP** on `0.0.0.0:8000`. Consumers
that reach it from an **HTTPS** context hit failures:

- **ttrpg2 dashboard** (`/area`) is served over HTTPS but injects
  `<script src="http://192.168.86.29:8000/dungml-play.js">` and the widget then
  makes browser calls to the same HTTP origin → **mixed-content**, blocked by the
  browser.
- Serving the dungml SPA itself over plain HTTP on a LAN IP (not `localhost`)
  puts it in a **non-secure context**, where `window.crypto.subtle` is
  unavailable — so `oidc-client-ts` PKCE (which needs Web Crypto) cannot run.

Goal: dungml serves over **HTTPS** using the existing shared cert, and every
consumer (ttrpg3 server-side proxy, ttrpg2 dashboard + tools) is updated so the
whole system keeps working end-to-end.

## Decisions (confirmed)

- **Scope:** full system — dungml serving + ttrpg3 + ttrpg2, plus a Keycloak
  admin checklist for the user.
- **TLS termination:** directly in uvicorn (mirrors ttrpg3's own TLS), **not** a
  separate reverse proxy.
- **Cert:** reuse the shared self-signed pair `/home/raf/roleplaying/certs/server.crt`
  + `server.key` (SAN already covers `192.168.86.29`, `192.168.86.28`,
  `localhost`, `127.0.0.1`); CA is `/home/raf/roleplaying/certs/ca.crt`.
- **Port:** unchanged — `8000`, now `https`.

## Architecture: who reaches dungml, and how

| Consumer | Path to dungml | Mixed-content? | Change needed |
|---|---|---|---|
| dungml SPA (browser, direct) | same-origin | n/a | serve HTTPS (secure context for PKCE) |
| ttrpg3 browser widget | **same-origin proxy** via ttrpg3 (`/api/instances/{id}/dungml/play.js`) | no | none (browser side) |
| ttrpg3 backend proxy | server→server httpx to `DD_DUNGML_URL` | n/a | https URL + CA trust |
| ttrpg2 dashboard `/area` | **browser loads dungml directly** (`{api_base}/dungml-play.js`) | **yes** | api_base → https (browser trusts CA already) |
| ttrpg2 python tools | server→server urllib to `DUNGML_API_BASE` | n/a | https URL + CA trust |

Browser trust: the user's browser already trusts this CA (ttrpg3's frontend runs
HTTPS with it), so browser→dungml HTTPS works without warnings. Only the
**server-side** Python HTTP clients need explicit CA trust.

## Changes by repo

### 1. dungml — **no code change** (config only)

`main.py:run()` already reads `DUNGML_SSL_CERTFILE`/`DUNGML_SSL_KEYFILE` and
passes them to `uvicorn.run`, and `ttrpg3/scripts/dungml.sh` already exports every
`DUNGML_*` line from ttrpg3's repo-root `.env`. So TLS is enabled purely by
config in that `.env`:

```
DUNGML_SSL_CERTFILE=/home/raf/roleplaying/certs/server.crt
DUNGML_SSL_KEYFILE=/home/raf/roleplaying/certs/server.key
```

Document the two vars in `ttrpg3/.env.example`. Relaunch dungml via
`ttrpg3/scripts/dev.sh --dungml` (or `dungml.sh`).

### 2. ttrpg3 — code + config

- `.env`: `DD_DUNGML_URL=https://192.168.86.29:8000`; add
  `DD_DUNGML_CA_CERT=../certs/ca.crt`. Document both in `.env.example`.
- `apps/api/src/dungeon_daemon/api/config.py`: add `dungml_ca_cert: str = ""`
  (adjacent to `dungml_url: str = ""` at line ~124).
- `apps/api/src/dungeon_daemon/api/backends.py`: add a module helper that turns a
  CA-cert path into an httpx `verify` value, mirroring the existing `_kc_post`
  pattern (`ssl.create_default_context(cafile=ca)` when set, else `True`):

  ```python
  def _dungml_verify(ca_cert: str):
      if not ca_cert:
          return True
      import ssl
      return ssl.create_default_context(cafile=ca_cert)
  ```

  Thread `verify` into **all six** ttrpg3→dungml httpx call sites (each currently
  calls httpx with default verification):
  - `_dungml_transport` (line ~308, `httpx.request`) — build `verify` once in the
    closure; add a `ca_cert: str = ""` param; caller at line ~421 passes
    `s.dungml_ca_cert`.
  - `fetch_map_render` (~434, `httpx.get`), `fetch_campaign_map_render` (~448),
    `fetch_map_info` (~473), `dungml_get` (~489), `dungml_post` (~500): accept the
    CA cert (thread from the caller's `Settings`) and pass `verify=`.

  Empty CA → `True` (system trust) preserves current behavior, so existing tests
  pass unchanged; test hosts like `http://dungml.test` stay on http.

### 3. ttrpg2 — code + config

- Point the API base at HTTPS by flipping **only the scheme**, preserving each
  module's existing host (the cert covers both `192.168.86.29` and `127.0.0.1`):
  `tools/_dungml_http.py` `_DEFAULT_BASE` → `https://192.168.86.29:8000`;
  `tools/combat_map.py` `DUNGML_API_BASE` default → `https://127.0.0.1:8000`.
  Set `DUNGML_API_BASE=https://192.168.86.29:8000` in ttrpg2's runtime
  `.env`/README (the dashboard host, browser-facing). This flips the `/area`
  script tag and `/dungml-play-config` `base_url` (both derived from
  `_dh.api_base()`) to HTTPS → mixed content resolved.
- Both modules use `urllib.request.urlopen`, which needs an explicit SSL context
  to trust the private CA. Add a shared helper in `tools/_dungml_http.py`:

  ```python
  import ssl
  def dungml_ssl_context():
      """SSL context trusting the dungml TLS CA, for urllib https calls.
      None when unset (http URLs ignore it; https falls back to system trust)."""
      ca = os.environ.get("DUNGML_CA_CERT", "")
      return ssl.create_default_context(cafile=ca) if ca else None
  ```

  Pass `context=dungml_ssl_context()` to `urlopen` in `_dungml_http._http()` and
  import+use it in `combat_map._dungml_render()`. Set
  `DUNGML_CA_CERT=/home/raf/roleplaying/certs/ca.crt` in ttrpg2's env.

### 4. Keycloak — admin checklist (user performs; no code)

On the `dungml-web` realm client:
- **Valid Redirect URIs:** add `https://192.168.86.29:8000/*` (the dungml origin
  is now https; oidc-client-ts uses `window.location.origin` as `redirect_uri`).
- **Web Origins:** add `https://192.168.86.29:8000`.
- The old `http://192.168.86.29:8000` entries can be removed once HTTP is retired.

## Data flow (after change)

Browser → `https://…:8000` dungml SPA (secure context, PKCE works) → OIDC against
`https://…:8443` Keycloak. ttrpg2 `/area` (https) → loads
`https://…:8000/dungml-play.js` (browser trusts CA) → widget calls
`https://…:8000/api/...`. Server-side: ttrpg3 & ttrpg2 Python clients →
`https://…:8000` verifying against `ca.crt`.

## Testing

- **dungml serving:** `curl -sk https://127.0.0.1:8000/api/dsl/renderers` → 200;
  plain `curl http://127.0.0.1:8000/...` → connection reset/refused (TLS-only).
  `curl --cacert /home/raf/roleplaying/certs/ca.crt https://127.0.0.1:8000/...`
  → 200 (verifies the cert chain, not just `-k`).
- **ttrpg3 (unit):** tests for `_dungml_verify` — empty CA returns `True`;
  non-empty returns an `ssl.SSLContext`. Existing `dungml_url="http://dungml.test"`
  tests remain green (default empty CA). Add/adjust a test asserting the CA is
  threaded to a call site (e.g. `_dungml_transport` builds the context when
  `dungml_ca_cert` is set).
- **ttrpg3 (live):** with dungml on HTTPS, a map render/create through the ttrpg3
  proxy succeeds (no TLS verification error).
- **ttrpg2 (live):** `_dungml_http` login/map-fetch and `combat_map._dungml_render`
  succeed against `https://…:8000` with `DUNGML_CA_CERT` set; `/area` loads the
  widget with no browser mixed-content/cert error.

## Edge cases / notes

- **CA unset + https URL:** server-side urllib/httpx fall back to system trust and
  will fail on the self-signed cert — the fix is to set the CA env, which this
  spec does in each repo's config.
- **http fallback preserved:** empty CA + http URL is unchanged, so test suites
  and any localhost-http usage keep working.
- **CORS:** dungml `DUNGML_CORS_ORIGINS` defaults to `*`; browser calls from the
  ttrpg2 origin are already permitted. No change.
- **JWKS URL unaffected:** dungml→Keycloak JWKS stays `http://…:8080`
  (server-side, plain http to KC's http port) — independent of dungml's own TLS.

## Out of scope (YAGNI)

- Retiring HTTP entirely / HTTP→HTTPS redirect (uvicorn serves one scheme; nothing
  needs a redirector here).
- Replacing the self-signed cert with a CA-issued one.
- Restricting `DUNGML_CORS_ORIGINS` from `*`.
- Any change to the dungml SPA build (same-origin API + `window.location.origin`
  redirect already adapt to https automatically).
