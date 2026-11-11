# Half-set sign-in refused at startup

The deployed server signs users in with Entra OAuth when `AUTH_CLIENT_ID` is set. A config with only some of the four sign-in settings (`AUTH_CLIENT_ID`, `AUTH_CLIENT_SECRET`, `AUTH_TENANT_ID`, `PUBLIC_BASE_URL`) must refuse to start with a clear message naming what is missing. With all four unset, local mode still serves on `127.0.0.1`, and a public bind is refused.

## Sub-features

Each name is a case in `signin_matrix.py` and a `signin-<name>.log` in evidence.

- `client-id-only`, `all-but-secret`, `whitespace-secret`: `AUTH_CLIENT_ID` without a secret, or with a whitespace secret, refuses with a message naming `AUTH_CLIENT_SECRET` (the PR #6 guard).
- `id-and-secret-no-tenant`, `all-but-public-base-url`: client id and secret set but `AUTH_TENANT_ID` or `PUBLIC_BASE_URL` missing refuses with a message naming the missing setting.
- `secret-only`, `tenant-and-url-only`: `AUTH_CLIENT_SECRET`, or tenant and URL, set without `AUTH_CLIENT_ID` refuses with a message naming `AUTH_CLIENT_ID`.
- `all-unset-loopback`: all four unset on `127.0.0.1` starts and lists the seven tools.
- `all-unset-public-bind`: all four unset on `0.0.0.0` refuses (the older fail-closed guard).
- No case prints the placeholder secret. The final Leak check in SKILL.md also scans every `signin-<case>.log` for it.

## How to get to it (user POV)

The user here is Brady (or whoever deploys). They set env vars on the Container App or in a shell and start `python -m friend_mcp.server` (or `jarvis-trading-mcp`). A friend never sees this directly: a server that starts half-configured either serves without sign-in or signs JWTs with a key derived from an empty secret.

`deploy.sh` has its own guard for client id without secret or tenant. That script calls `az`, so it is covered only by `tests/test_deploy_guard.py` with a stub `az`, never driven here.

## Driving it with signin_matrix.py

Preconditions:

- Launch passed (the matrix only needs the venv; the refusing cases exit before any upstream call, and the local case only lists tools).
- `SIGNIN_PORT` is free. The script checks this itself before the first case and exits naming the port if it is busy. Each case starts a real `python -m friend_mcp.server` on it, and the script stops each child itself by handle.

```bash
set -euo pipefail
. .cursor/skills/verify-jarvis-trading-mcp/vars.sh
.venv/bin/python "$SKILL_DIR/signin_matrix.py" --repo "$PWD" --python "$PWD/.venv/bin/python" \
  --port "$SIGNIN_PORT" --api "$API_URL" --evidence "$EVIDENCE"
```

A refusing case passes only if the process exits nonzero, never logs `Uvicorn running`, has no Python traceback, prints a line starting `refusing to start` that names the missing setting, and does not print the secret. `all-unset-loopback` passes only if it serves and `list_tools` returns the seven tools. Pass is nine `PASS` lines and `signin matrix ok`. Per-case output is in `signin-<case>.log`; the summary is `signin-matrix.json`.

## Gotchas

- A Python `KeyError` traceback does exit nonzero, but it is not a clear error. The matrix counts it as a failure on purpose. Do not relax the traceback check.
- The full four-setting case is not in the matrix. It builds the real `AzureProvider`, which this skill keeps off the network. `tests/test_startup_auth.py` covers it with `mcp.run` stubbed and a blackhole proxy.
- In `signin-matrix.json`, cases that served show `traceback: true` from the mcp SSE writer noise on session close (see SKILL.md Evidence). The traceback check applies only to refusing cases.
- An empty `AUTH_CLIENT_ID=""` counts as unset, so the server starts in local mode. That is intended.
- Every child gets both cases of `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` set to `http://127.0.0.1:9`, loopback `NO_PROXY`/`no_proxy` (any inherited proxy variable of either case is dropped first), no inherited `AZURE_*`, `IDENTITY_*`, or `MSI_*`, `MSI_ENDPOINT`/`IDENTITY_ENDPOINT` on `http://127.0.0.1:9`, placeholder ids, and a loopback `JARVIS_TRADING_API`.
- Known failures on main 57efd10 (verify run 2026-11-10): `id-and-secret-no-tenant` and `all-but-public-base-url` exit with a raw `KeyError` traceback (`friend_mcp/server.py:62` and `:64`), and `secret-only` and `tenant-and-url-only` start in unauthenticated local mode because the guard at `friend_mcp/server.py:51` keys only on `AUTH_CLIENT_ID`. These are product gaps. Leave the matrix red until the server is fixed.
