# dungml over TLS (system-wide) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve dungml over HTTPS with the shared self-signed cert and update every consumer (ttrpg3 proxy, ttrpg2 dashboard + tools) so the system works end-to-end and the ttrpg2 mixed-content error is gone.

**Architecture:** dungml terminates TLS directly in uvicorn via its existing `DUNGML_SSL_*` support (no dungml code change). Server-side Python HTTP clients (ttrpg3 httpx, ttrpg2 urllib) get explicit private-CA trust; browser trust already exists. Config lives in each repo's gitignored `.env`; only `.env.example`/README are committed.

**Tech Stack:** uvicorn/FastAPI (dungml), httpx (ttrpg3), urllib + stdlib ssl (ttrpg2). Design ref: `docs/superpowers/specs/2026-07-03-dungml-tls-design.md`.

## Global Constraints

- **Cert (reuse):** `/home/raf/roleplaying/certs/server.crt` + `server.key`; CA `/home/raf/roleplaying/certs/ca.crt`. SAN covers `192.168.86.29`, `127.0.0.1`, `localhost`.
- **No new dependencies** in any repo. No dungml code change (config only).
- **Backward-compatible default:** empty CA cert ⇒ `verify=True` (httpx) / `context=None` (urllib) ⇒ existing behavior and tests unchanged. HTTP URLs keep working.
- **Repos & where changes land** (this plan spans three git repos):
  - `dungml` (branch `feat/dungml-tls`): planning docs only — no code.
  - `ttrpg3` (`/home/raf/roleplaying/ttrpg3`): code + config. ⚠️ Currently on branch `feat/player-input-styling` with **unrelated uncommitted changes** (`apps/api/src/dungeon_daemon/api/main.py`, `apps/api/tests/test_jester_api.py`, `apps/web/src/ModelTierControl.test.tsx`) — the controller must confirm branch strategy before committing here (do NOT stash/switch away from the user's WIP without asking).
  - `ttrpg2` (`/home/raf/roleplaying/ttrpg2`): code + config; branch off `main`.
- **`.env` is gitignored** in ttrpg3 and ttrpg2 → local `.env` edits are NOT committed; commit only `.env.example` / `README.md`.
- **Test commands:**
  - ttrpg3: `cd /home/raf/roleplaying/ttrpg3/apps/api && uv run pytest tests/<file> -q` (a pre-existing `StarletteDeprecationWarning` about httpx/testclient appears in output — NOT a regression).
  - ttrpg2: `cd /home/raf/roleplaying/ttrpg2 && .venv/bin/python -m unittest tests.<module> -v` (stdlib unittest; no pytest).

---

### Task 1: Enable TLS on dungml serving (ttrpg3 `.env` config)

dungml's `main.py:run()` already passes `DUNGML_SSL_CERTFILE`/`DUNGML_SSL_KEYFILE` to uvicorn, and `ttrpg3/scripts/dungml.sh` exports every `DUNGML_*` line from ttrpg3's repo-root `.env`. So this task is config + a live TLS verification. No source code changes.

**Files:**
- Modify (local, gitignored): `/home/raf/roleplaying/ttrpg3/.env`
- Modify (committed): `/home/raf/roleplaying/ttrpg3/.env.example`

**Interfaces:**
- Produces: dungml reachable at `https://…:8000`; the env vars `DUNGML_SSL_CERTFILE`/`DUNGML_SSL_KEYFILE` documented for consumers.

- [ ] **Step 1: Add the SSL env to ttrpg3's local `.env`**

Append these two lines to `/home/raf/roleplaying/ttrpg3/.env`:
```
DUNGML_SSL_CERTFILE=/home/raf/roleplaying/certs/server.crt
DUNGML_SSL_KEYFILE=/home/raf/roleplaying/certs/server.key
```

- [ ] **Step 2: Document them in the committed `.env.example`**

Add the same two lines (with a brief comment) to `/home/raf/roleplaying/ttrpg3/.env.example`, near the other `DUNGML_*` lines:
```
# dungml serves HTTPS directly in uvicorn using the shared cert (dungml.sh
# exports these; main.py passes them to uvicorn). Browser needs the CA trusted.
DUNGML_SSL_CERTFILE=/home/raf/roleplaying/certs/server.crt
DUNGML_SSL_KEYFILE=/home/raf/roleplaying/certs/server.key
```

- [ ] **Step 3: Verify TLS wiring with a throwaway instance on a free port**

Do not disturb the running :8000. Start a temporary dungml on port 8009 with the SSL env, from the dungml checkout:
```bash
cd /home/raf/roleplaying/dungml
DUNGML_PORT=8009 \
DUNGML_SSL_CERTFILE=/home/raf/roleplaying/certs/server.crt \
DUNGML_SSL_KEYFILE=/home/raf/roleplaying/certs/server.key \
uv run dmap-server &
DMAP_PID=$!
sleep 4
```
Expected: startup log shows `Uvicorn running on https://0.0.0.0:8009`.

- [ ] **Step 4: Confirm HTTPS serves and HTTP does not**

```bash
echo "--- https with CA trust (expect 200) ---"
curl -s -o /dev/null -w "%{http_code}\n" --cacert /home/raf/roleplaying/certs/ca.crt https://127.0.0.1:8009/api/dsl/renderers
echo "--- plain http against the TLS port (expect failure) ---"
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8009/api/dsl/renderers || echo "http refused (expected)"
kill "$DMAP_PID" 2>/dev/null
```
Expected: first prints `200`; second fails/prints a non-200 or curl error (TLS-only port).

- [ ] **Step 5: Commit (ttrpg3 repo — `.env.example` only)**

```bash
cd /home/raf/roleplaying/ttrpg3
git add .env.example
git commit -m "docs(env): document DUNGML_SSL_CERTFILE/KEYFILE for dungml TLS

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: ttrpg3 — `dungml_ca_cert` setting + `_dungml_verify` helper + wire into map service

**Files:**
- Modify: `/home/raf/roleplaying/ttrpg3/apps/api/src/dungeon_daemon/api/config.py` (add `dungml_ca_cert`, next to `dungml_url`)
- Modify: `/home/raf/roleplaying/ttrpg3/apps/api/src/dungeon_daemon/api/backends.py` (add `_dungml_verify`; thread into `_dungml_transport` + its caller `get_map_service`)
- Test: `/home/raf/roleplaying/ttrpg3/apps/api/tests/test_dungml_proxy.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `Settings.dungml_ca_cert: str = ""`.
  - `_dungml_verify(ca_cert: str)` → `True` when empty, else an `ssl.SSLContext`.
  - `_dungml_transport(url, get_token, ca_cert="")` — now applies `verify` to its httpx call.

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/test_dungml_proxy.py`:
```python
import os
import ssl

import httpx

from dungeon_daemon.api.backends import _dungml_transport, _dungml_verify

_CA = "/home/raf/roleplaying/certs/ca.crt"


def test_dungml_verify_empty_is_true():
    assert _dungml_verify("") is True


def test_dungml_verify_cafile_builds_context():
    if not os.path.exists(_CA):
        import pytest
        pytest.skip("CA cert not present on this host")
    assert isinstance(_dungml_verify(_CA), ssl.SSLContext)


def test_dungml_transport_passes_verify(monkeypatch):
    captured = {}

    class _Resp:
        content = b"{}"
        def raise_for_status(self):
            return None
        def json(self):
            return {}

    def _fake_request(method, url, **kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr(httpx, "request", _fake_request)
    transport = _dungml_transport("https://dungml.test", lambda: "tok", ca_cert="")
    transport("GET", "/x", {})
    assert captured["verify"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/raf/roleplaying/ttrpg3/apps/api && uv run pytest tests/test_dungml_proxy.py -q`
Expected: FAIL — `ImportError: cannot import name '_dungml_verify'`.

- [ ] **Step 3: Add `dungml_ca_cert` to `config.py`**

In `apps/api/src/dungeon_daemon/api/config.py`, immediately after the `dungml_url: str = ""` line, add:
```python
    # Private-CA cert (PEM) trusted for https calls to dungml's self-signed TLS.
    # Empty → system trust (unchanged for http/test hosts). Mirrors keycloak_ca_cert.
    dungml_ca_cert: str = ""
```

- [ ] **Step 4: Add `_dungml_verify` and thread it into `_dungml_transport`**

In `apps/api/src/dungeon_daemon/api/backends.py`, add the helper just above `_dungml_transport`:
```python
def _dungml_verify(ca_cert: str):
    """httpx `verify` value for calls to dungml. Empty → True (system trust);
    a PEM path → an SSLContext trusting that private CA (self-signed dungml TLS).
    Mirrors the CA handling in _kc_post."""
    if not ca_cert:
        return True
    import ssl

    return ssl.create_default_context(cafile=ca_cert)
```
Then replace `_dungml_transport` with:
```python
def _dungml_transport(url: str, get_token: Callable[[], str], ca_cert: str = ""):
    """HTTP transport for DungmlMapService (lazy httpx). `get_token` returns the
    current bearer, read per request. `ca_cert` trusts dungml's self-signed TLS."""
    import httpx

    base = url.rstrip("/")
    verify = _dungml_verify(ca_cert)

    def transport(method: str, path: str, json: dict) -> dict:
        token = get_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        resp = httpx.request(method, f"{base}{path}", json=json, headers=headers, timeout=10, verify=verify)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    return transport
```
In `get_map_service`, update the construction (currently `_dungml_transport(s.dungml_url, get_token)`) to pass the CA:
```python
        return DungmlMapService(_dungml_transport(s.dungml_url, get_token, s.dungml_ca_cert))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/raf/roleplaying/ttrpg3/apps/api && uv run pytest tests/test_dungml_proxy.py -q`
Expected: PASS (existing proxy tests + 3 new; the pre-existing StarletteDeprecationWarning may appear — ignore it).

- [ ] **Step 6: Commit (ttrpg3 repo)**

```bash
cd /home/raf/roleplaying/ttrpg3
git add apps/api/src/dungeon_daemon/api/config.py apps/api/src/dungeon_daemon/api/backends.py apps/api/tests/test_dungml_proxy.py
git commit -m "feat(ttrpg3): dungml_ca_cert + _dungml_verify; trust dungml TLS in map service

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: ttrpg3 — thread CA trust through the 6 proxy/fetch functions + callers + activate config

**Files:**
- Modify: `/home/raf/roleplaying/ttrpg3/apps/api/src/dungeon_daemon/api/backends.py` (6 functions)
- Modify: `/home/raf/roleplaying/ttrpg3/apps/api/src/dungeon_daemon/api/main.py` (10 call sites)
- Modify (local): `/home/raf/roleplaying/ttrpg3/.env`; Modify (committed): `/home/raf/roleplaying/ttrpg3/.env.example`
- Test: `/home/raf/roleplaying/ttrpg3/apps/api/tests/test_dungml_proxy.py` (append)

**Interfaces:**
- Consumes: `_dungml_verify` and `Settings.dungml_ca_cert` from Task 2.
- Produces: `fetch_map_render`, `fetch_campaign_map_render`, `fetch_map_info`, `dungml_get`, `dungml_post`, `dungml_delete` all accept `ca_cert: str = ""` and pass `verify` to httpx.

- [ ] **Step 1: Write the failing test**

Append to `apps/api/tests/test_dungml_proxy.py`:
```python
def test_fetch_map_render_passes_verify(monkeypatch):
    from dungeon_daemon.api import backends as b

    captured = {}

    class _Resp:
        content = b"svg"
        def raise_for_status(self):
            return None

    def _fake_get(url, **kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr(httpx, "get", _fake_get)
    b.fetch_map_render("https://dungml.test", 1, "tok", ca_cert="")
    assert captured["verify"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/raf/roleplaying/ttrpg3/apps/api && uv run pytest tests/test_dungml_proxy.py::test_fetch_map_render_passes_verify -q`
Expected: FAIL — `TypeError: fetch_map_render() got an unexpected keyword argument 'ca_cert'`.

- [ ] **Step 3: Add `ca_cert` + `verify` to the six functions in `backends.py`**

For each function, add a trailing `ca_cert: str = ""` parameter and pass `verify=_dungml_verify(ca_cert)` to its httpx call. Exact edits:

`fetch_map_render` — signature → `def fetch_map_render(dungml_url: str, instance_id: int, token: str, ca_cert: str = "") -> bytes:`; the `httpx.get(f"{dungml_url}/maps/{instance_id}/render", params={"token": token}, timeout=10)` gains `verify=_dungml_verify(ca_cert)`.

`fetch_campaign_map_render` — signature → `def fetch_campaign_map_render(dungml_url: str, instance_id: int, map_id: str, token: str, ca_cert: str = "") -> bytes:`; add `verify=_dungml_verify(ca_cert)` to its `httpx.get(...)`.

`fetch_map_info` — signature → `def fetch_map_info(dungml_url: str, instance_id: int, token: str, ca_cert: str = "") -> dict:`; add `verify=_dungml_verify(ca_cert)` to its `httpx.get(...)`.

`dungml_get` — signature → `def dungml_get(dungml_url: str, path: str, *, token: str | None = None, params: dict | None = None, ca_cert: str = "") -> tuple[int, bytes, str]:`; change its call to `resp = httpx.get(f"{dungml_url}{path}", headers=headers, params=params, timeout=10, verify=_dungml_verify(ca_cert))`.

`dungml_post` — signature → `def dungml_post(dungml_url: str, path: str, *, token: str | None = None, json: dict | None = None, ca_cert: str = "") -> tuple[int, bytes, str]:`; change its call to `resp = httpx.post(f"{dungml_url}{path}", headers=headers, json=json, timeout=10, verify=_dungml_verify(ca_cert))`.

`dungml_delete` — signature → `def dungml_delete(dungml_url: str, path: str, *, token: str | None = None, ca_cert: str = "") -> tuple[int, bytes, str]:`; change its call to `resp = httpx.delete(f"{dungml_url}{path}", headers=headers, timeout=10, verify=_dungml_verify(ca_cert))`.

- [ ] **Step 4: Pass `ca_cert` at all 10 call sites in `main.py`**

In `apps/api/src/dungeon_daemon/api/main.py`, add a `ca_cert=<VAR>.dungml_ca_cert` argument to each dungml call below, where `<VAR>` is whatever settings variable already supplies `.dungml_url` in that same call (`settings` or `s`). The call sites (add the kwarg to each):
- L3863 `fetch_campaign_map_render(settings.dungml_url, instance_id, map_id, token)` → append `, ca_cert=settings.dungml_ca_cert`
- L3873 `fetch_map_render(settings.dungml_url, instance_id, token)` → append `, ca_cert=settings.dungml_ca_cert`
- L3902 `fetch_map_info(s.dungml_url, instance_id, token)` → append `, ca_cert=s.dungml_ca_cert`
- L3912 `dungml_get(s.dungml_url, path, token=token, params=params)` → append `, ca_cert=s.dungml_ca_cert`
- L3926 `dungml_get(...)` (multiline) → add `ca_cert=s.dungml_ca_cert`
- L3944 `dungml_post(...)` (multiline) → add `ca_cert=s.dungml_ca_cert`
- L3966 `dungml_post(...)` (multiline) → add `ca_cert=s.dungml_ca_cert`
- L3994 `dungml_delete(...)` (multiline) → add `ca_cert=s.dungml_ca_cert`
- L4014 `dungml_get(s.dungml_url, "/dungml-play.js", token=token)` → append `, ca_cert=s.dungml_ca_cert`
- L4046 `dungml_post(...)` (multiline) → add `ca_cert=s.dungml_ca_cert`

Rule for the multiline ones: match the settings variable already used for `.dungml_url` in that call and add the sibling `.dungml_ca_cert`. Verify none are missed:
```bash
cd /home/raf/roleplaying/ttrpg3
grep -nE "fetch_map_render|fetch_campaign_map_render|fetch_map_info|dungml_get|dungml_post|dungml_delete" apps/api/src/dungeon_daemon/api/main.py | grep -v ca_cert
```
Expected: no lines printed (every call now carries `ca_cert`).

- [ ] **Step 5: Activate config — ttrpg3 `.env` + `.env.example`**

In `/home/raf/roleplaying/ttrpg3/.env`: change `DD_DUNGML_URL=http://192.168.86.29:8000` to `DD_DUNGML_URL=https://192.168.86.29:8000` and add `DD_DUNGML_CA_CERT=../certs/ca.crt`.
In `/home/raf/roleplaying/ttrpg3/.env.example`: reflect the same (https example URL + a documented `DD_DUNGML_CA_CERT=../certs/ca.crt`).

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /home/raf/roleplaying/ttrpg3/apps/api && uv run pytest tests/test_dungml_proxy.py -q`
Expected: PASS (all proxy tests including the new verify test). Then run the broader dungml-related suite to confirm no regressions:
Run: `cd /home/raf/roleplaying/ttrpg3/apps/api && uv run pytest tests/test_dungml_proxy.py tests/test_dungml_projects.py tests/test_dungml_campaign_link.py tests/test_map_switcher.py tests/test_api.py -q`
Expected: PASS (pre-existing StarletteDeprecationWarning aside).

- [ ] **Step 7: Commit (ttrpg3 repo)**

```bash
cd /home/raf/roleplaying/ttrpg3
git add apps/api/src/dungeon_daemon/api/backends.py apps/api/src/dungeon_daemon/api/main.py apps/api/tests/test_dungml_proxy.py .env.example
git commit -m "feat(ttrpg3): trust dungml TLS CA across all proxy/fetch calls; point at https

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: ttrpg2 — `dungml_ssl_context()` helper, apply to urllib calls, flip to https

**Files:**
- Modify: `/home/raf/roleplaying/ttrpg2/tools/_dungml_http.py` (add helper; use `context=`; default base → https)
- Modify: `/home/raf/roleplaying/ttrpg2/tools/combat_map.py` (import helper; use `context=`; default base → https)
- Modify (local): `/home/raf/roleplaying/ttrpg2/.env`; Modify (committed): `/home/raf/roleplaying/ttrpg2/README.md`
- Test: `/home/raf/roleplaying/ttrpg2/tests/test_dungml_ssl.py` (create)

**Interfaces:**
- Produces: `tools._dungml_http.dungml_ssl_context()` → `None` when `DUNGML_CA_CERT` unset, else an `ssl.SSLContext`.

- [ ] **Step 1: Write the failing test**

Create `/home/raf/roleplaying/ttrpg2/tests/test_dungml_ssl.py`:
```python
"""Unit tests for tools._dungml_http.dungml_ssl_context.

Run: python3 -m unittest tests.test_dungml_ssl
"""
from __future__ import annotations

import os
import ssl
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools._dungml_http import dungml_ssl_context

_CA = "/home/raf/roleplaying/certs/ca.crt"


class DungmlSslContextTests(unittest.TestCase):
    def test_none_when_unset(self):
        os.environ.pop("DUNGML_CA_CERT", None)
        self.assertIsNone(dungml_ssl_context())

    def test_context_when_set(self):
        if not os.path.exists(_CA):
            self.skipTest("CA cert not present on this host")
        os.environ["DUNGML_CA_CERT"] = _CA
        try:
            self.assertIsInstance(dungml_ssl_context(), ssl.SSLContext)
        finally:
            os.environ.pop("DUNGML_CA_CERT", None)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/raf/roleplaying/ttrpg2 && .venv/bin/python -m unittest tests.test_dungml_ssl -v`
Expected: FAIL — `ImportError: cannot import name 'dungml_ssl_context'`.

- [ ] **Step 3: Add the helper + apply it in `_dungml_http.py`**

In `/home/raf/roleplaying/ttrpg2/tools/_dungml_http.py`:
1. Add `import ssl` to the imports.
2. Change the default base: `_DEFAULT_BASE = "https://192.168.86.29:8000"`.
3. Add the helper (after `api_base()`):
```python
def dungml_ssl_context():
    """SSL context trusting the dungml TLS private CA for https urllib calls.
    None when DUNGML_CA_CERT is unset (http URLs ignore it; https then falls
    back to system trust)."""
    ca = os.environ.get("DUNGML_CA_CERT", "")
    return ssl.create_default_context(cafile=ca) if ca else None
```
4. In `_http`, pass the context to `urlopen`:
```python
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S, context=dungml_ssl_context()) as resp:
```

- [ ] **Step 4: Apply it in `combat_map.py`**

In `/home/raf/roleplaying/ttrpg2/tools/combat_map.py`:
1. Change the default: `DUNGML_API_BASE = os.environ.get("DUNGML_API_BASE", "https://127.0.0.1:8000").rstrip("/")`.
2. Import the helper near the top (after the existing imports): `from tools._dungml_http import dungml_ssl_context`.
3. In `_dungml_render`, pass the context to its `urlopen`:
```python
        with urllib.request.urlopen(req, timeout=_DUNGML_TIMEOUT_S, context=dungml_ssl_context()) as resp:
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/raf/roleplaying/ttrpg2 && .venv/bin/python -m unittest tests.test_dungml_ssl -v`
Expected: PASS (2 tests; `test_context_when_set` passes since the CA exists on this host).

- [ ] **Step 6: Config + docs — ttrpg2 `.env` + README**

In `/home/raf/roleplaying/ttrpg2/.env` (local, gitignored): set
```
DUNGML_API_BASE=https://192.168.86.29:8000
DUNGML_CA_CERT=/home/raf/roleplaying/certs/ca.crt
```
In `/home/raf/roleplaying/ttrpg2/README.md`: update the `DUNGML_API_BASE=http://127.0.0.1:8000` line to the https value and add a `DUNGML_CA_CERT=/home/raf/roleplaying/certs/ca.crt` line with a one-line note that dungml now serves TLS and the CA must be trusted.

- [ ] **Step 7: Commit (ttrpg2 repo)**

```bash
cd /home/raf/roleplaying/ttrpg2
git add tools/_dungml_http.py tools/combat_map.py tests/test_dungml_ssl.py README.md
git commit -m "feat(ttrpg2): serve/reach dungml over https; trust TLS CA in urllib clients

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Manual verification checklist (controller + user; not a subagent task)

These require the live system and Keycloak admin access — run after Tasks 1-4.

- [ ] **Keycloak (user, admin console):** on the `dungml-web` client, add `https://192.168.86.29:8000/*` to **Valid Redirect URIs** and `https://192.168.86.29:8000` to **Web Origins**. (Remove the `http://…:8000` entries once HTTP is retired.)
- [ ] **Relaunch dungml** (user; via `ttrpg3/scripts/dev.sh --dungml`) so it picks up the new `DUNGML_SSL_*` env → serves `https://…:8000`. Confirm: `curl -s --cacert /home/raf/roleplaying/certs/ca.crt https://192.168.86.29:8000/api/dsl/renderers` → 200.
- [ ] **Relaunch ttrpg3 backend** so it reads `DD_DUNGML_URL`/`DD_DUNGML_CA_CERT`; open a map in ttrpg3 and confirm render/create works (no TLS error in logs).
- [ ] **ttrpg2 `/area`:** load the page; confirm the dungml play widget loads with no browser mixed-content/cert error, and `combat_map` map creation succeeds against `https://…:8000`.
- [ ] **dungml SPA (direct):** hard-refresh; confirm Keycloak login completes over HTTPS (secure context — PKCE works) and the header shows the username.

## Self-Review

**Spec coverage:**
- dungml serves TLS via `DUNGML_SSL_*` (config, no code) → Task 1. ✓
- ttrpg3 `dungml_ca_cert` setting + `_dungml_verify` + `_dungml_transport` → Task 2. ✓
- All six ttrpg3 proxy/fetch functions + 10 callers get CA trust; `DD_DUNGML_URL`→https + `DD_DUNGML_CA_CERT` → Task 3. ✓
- ttrpg2 `dungml_ssl_context()` + both urllib modules + https defaults + `DUNGML_API_BASE`/`DUNGML_CA_CERT` → Task 4. ✓
- Keycloak redirect/origin + end-to-end live checks → Manual checklist. ✓
- Cert reuse, no new deps, empty-CA backward compatibility, gitignored `.env` → Global Constraints, honored per task. ✓

**Placeholder scan:** No TBD/TODO. The `main.py` multiline call sites are specified by exact line + a concrete mechanical rule (match the sibling `.dungml_url` variable) + a grep gate that fails if any call is missed — not a vague instruction.

**Type consistency:** `_dungml_verify(ca_cert: str)` defined in Task 2, used in Task 3's six functions with identical name/signature. `Settings.dungml_ca_cert` (Task 2) consumed as `settings.dungml_ca_cert`/`s.dungml_ca_cert` (Task 3). `dungml_ssl_context()` (Task 4) returns `None`|`ssl.SSLContext`, consumed via `context=` in both ttrpg2 modules. Test import `httpx` is module-level in the test file (Task 2 adds it) and reused by Task 3's test in the same file.
