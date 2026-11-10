---
name: verify-jarvis-trading-mcp
description: Verify jarvis-trading-mcp, a streamable-HTTP MCP server with seven read-only research tools, by driving it with a FastMCP client against a loopback paper backend and a file-backed fake Key Vault. Covers every tool, the 401 token reread and retry, and the half-set sign-in startup guard. Use before opening or updating a PR, or when a tool, the token path, or startup auth changes.
---

# Verify jarvis-trading-mcp

Users reach this app as an MCP connector (Claude or any streamable-HTTP client). There is no web UI. `friend_mcp/server.py` exposes seven tools and turns each call into one authenticated GET (two on a 401 that a token reread fixes). Locally the process is `python -m friend_mcp.server` on `HOST`/`PORT` (default port 8080), path `/mcp`.

`run-local.sh` is not the verify path. It shells out to macOS `security` and leaves `JARVIS_TRADING_API` pointed at the deployed research API. This skill starts a paper backend instead. The server has no dry-run flag: a non-loopback `JARVIS_TRADING_API` is a live call. Never run `az`, and never point `KEY_VAULT_URL` at a real vault.

Launch starts three processes:

| Process | Port var (default) | Token source | Used by |
| --- | --- | --- | --- |
| `paper_backend.py` | `PAPER_PORT` (8765) | accepts `paper` and whatever is in `$SCRATCH/paper-token` | everything |
| main server | `MCP_PORT` (8080) | `JARVIS_TRADING_TOKEN=paper` | the seven tool features |
| rotation server | `ROT_PORT` (8081) | fake Key Vault (`fake_kv/` on `PYTHONPATH`, reads `$SCRATCH/kv-secret`) | [token-reread](features/token-reread.md) |

`signin_matrix.py` starts its own short-lived servers on `SIGNIN_PORT` (8082) and stops each one itself.

The rotation server needs the Key Vault branch of `_read_token_source`, because that is the only source a running process can reread with a new value (an env var cannot change under a live process). `fake_kv/azure/` is a regular package that shadows the real Azure SDK when it is first on `PYTHONPATH`. It reads one local file, logs each read with the last 4 characters only, refuses any `KEY_VAULT_URL` that is not `*.invalid`, and opens no socket. Launch proves the shadowing works before the rotation server starts.

All settings live in `vars.sh`. Every block below sources it from the repository root. Export `EVIDENCE` and the ports in the same shell before each block, or every block falls back to the defaults and you end up with processes in the default evidence dir. Other agents may hold the default ports on a shared box; Launch names any busy port. To run a second copy side by side, export different `PAPER_PORT`, `MCP_PORT`, `ROT_PORT`, `SIGNIN_PORT`, and `EVIDENCE` first. Rate limiter and token cache are per process, so pairs do not collide. `HOST` stays `127.0.0.1` (a public bind without `AUTH_CLIENT_ID` exits).

Evidence goes to `$EVIDENCE` (default `/tmp/verify-jarvis-trading-mcp`) and survives Cleanup. Token files go to `$SCRATCH` (default `/tmp/verify-jarvis-trading-mcp-scratch-$PAPER_PORT`), which Cleanup removes.

## Launch

```bash
set -euo pipefail
. .cursor/skills/verify-jarvis-trading-mcp/vars.sh
test -x .venv/bin/python || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
unset AUTH_CLIENT_ID AUTH_CLIENT_SECRET AUTH_TENANT_ID PUBLIC_BASE_URL \
  KEY_VAULT_URL JARVIS_TOKEN_SECRET_NAME ALLOW_UNAUTHENTICATED JARVIS_TRADING_TOKEN
mkdir -p "$EVIDENCE" "$SCRATCH"
for p in paper mcp rot; do
  if [ -s "$EVIDENCE/$p.pid" ] && kill -0 "$(cat "$EVIDENCE/$p.pid")" 2>/dev/null; then
    echo "$p from an earlier run is still up; run Cleanup first" >&2; exit 1
  fi
done
# Remove only files this skill wrote on an earlier run. Never rm -rf EVIDENCE: it may be shared.
rm -f "$EVIDENCE"/{paper,server,rot-server}.log "$EVIDENCE"/{paper,mcp,rot}.pid \
  "$EVIDENCE"/paper-access.jsonl "$EVIDENCE"/fake-kv-reads.jsonl "$EVIDENCE"/tools*.json \
  "$EVIDENCE"/call-*.json "$EVIDENCE"/side-effects*.json "$EVIDENCE"/leakcheck.json \
  "$EVIDENCE"/signin-*.log "$EVIDENCE"/signin-matrix.json
# Fail early and by name if another process (another checkout, another agent) holds a port.
.venv/bin/python - "$PAPER_PORT" "$MCP_PORT" "$ROT_PORT" "$SIGNIN_PORT" <<'PY'
import socket, sys
busy = []
for port in map(int, sys.argv[1:]):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        busy.append(port)
    finally:
        s.close()
if busy:
    sys.exit(f"ports busy: {busy}; export other PAPER_PORT/MCP_PORT/ROT_PORT/SIGNIN_PORT")
PY
set_token "$SCRATCH/paper-token" "$ROT_OLD"
set_token "$SCRATCH/kv-secret" "$ROT_OLD"
NOPROXY_ENV=(HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 NO_PROXY=127.0.0.1,localhost)

PYTHONUNBUFFERED=1 .venv/bin/python "$SKILL_DIR/paper_backend.py" \
  --host 127.0.0.1 --port "$PAPER_PORT" \
  --access-log "$EVIDENCE/paper-access.jsonl" \
  --token-file "$SCRATCH/paper-token" \
  > "$EVIDENCE/paper.log" 2>&1 &
echo $! > "$EVIDENCE/paper.pid"
for _ in $(seq 1 60); do
  grep -q "paper backend ready $API_URL" "$EVIDENCE/paper.log" 2>/dev/null && break
  sleep 0.25
done
grep -q "paper backend ready $API_URL" "$EVIDENCE/paper.log"

env "${NOPROXY_ENV[@]}" PYTHONUNBUFFERED=1 \
  JARVIS_TRADING_TOKEN=paper JARVIS_TRADING_API="$API_URL" HOST=127.0.0.1 PORT="$MCP_PORT" \
  .venv/bin/python -m friend_mcp.server > "$EVIDENCE/server.log" 2>&1 &
echo $! > "$EVIDENCE/mcp.pid"

# The rotation server must load the fake SDK, never the real one.
PYTHONPATH="$PWD/$SKILL_DIR/fake_kv" .venv/bin/python -c '
import azure.identity as i, azure.keyvault.secrets as s
assert getattr(i.ManagedIdentityCredential, "fake", False), i.__file__
assert getattr(s.SecretClient, "fake", False), s.__file__
print("fake key vault shadows azure sdk:", s.__file__)'
env -u JARVIS_TRADING_TOKEN "${NOPROXY_ENV[@]}" PYTHONUNBUFFERED=1 \
  PYTHONPATH="$PWD/$SKILL_DIR/fake_kv" \
  KEY_VAULT_URL=https://fake-kv.invalid/ JARVIS_TOKEN_SECRET_NAME=verify-rotation \
  VERIFY_FAKE_KV_FILE="$SCRATCH/kv-secret" VERIFY_FAKE_KV_LOG="$EVIDENCE/fake-kv-reads.jsonl" \
  JARVIS_TRADING_API="$API_URL" HOST=127.0.0.1 PORT="$ROT_PORT" \
  .venv/bin/python -m friend_mcp.server > "$EVIDENCE/rot-server.log" 2>&1 &
echo $! > "$EVIDENCE/rot.pid"
touch "$EVIDENCE/fake-kv-reads.jsonl"

for log_port in "server.log:$MCP_PORT" "rot-server.log:$ROT_PORT"; do
  log=${log_port%%:*}; port=${log_port##*:}
  for _ in $(seq 1 80); do
    grep -q "Uvicorn running on http://127.0.0.1:${port}" "$EVIDENCE/$log" 2>/dev/null && break
    sleep 0.25
  done
  grep -q "Uvicorn running on http://127.0.0.1:${port}" "$EVIDENCE/$log"
done
echo "ready paper=${PAPER_PORT} mcp=${MCP_PORT} rot=${ROT_PORT}"
```

Readiness is three lines: `paper backend ready http://127.0.0.1:8765` in `paper.log`, then `Uvicorn running on http://127.0.0.1:8080` in `server.log` and `...:8081` in `rot-server.log`. The FastMCP "Starting MCP server" line is wrapped by the rich logger, so do not grep that sentence. If Launch fails partway, run Cleanup before retrying: it kills whichever pid files exist.

Both servers get `HTTP(S)_PROXY` pointed at a closed loopback port with `NO_PROXY=127.0.0.1`, so a stray non-loopback request fails instead of leaving the machine.

## Doctor

Read-only. Confirms the three processes are ours and alive, the rotation server has no env token, and both servers list the seven tools without adding a row to the paper access log.

```bash
set -euo pipefail
. .cursor/skills/verify-jarvis-trading-mcp/vars.sh
for p in paper mcp rot; do
  kill -0 "$(cat "$EVIDENCE/$p.pid")" || { echo "$p is not running" >&2; exit 1; }
done
if command -v ss >/dev/null; then
  for pp in "paper:$PAPER_PORT" "mcp:$MCP_PORT" "rot:$ROT_PORT"; do
    ss -ltnpH "sport = :${pp##*:}" | grep -q "pid=$(cat "$EVIDENCE/${pp%%:*}.pid")," \
      || { echo "port ${pp##*:} is not owned by ${pp%%:*}.pid" >&2; exit 1; }
  done
fi
if [ -r "/proc/$(cat "$EVIDENCE/rot.pid")/environ" ] \
  && tr '\0' '\n' < "/proc/$(cat "$EVIDENCE/rot.pid")/environ" | grep -q '^JARVIS_TRADING_TOKEN='; then
  echo "rotation server has JARVIS_TRADING_TOKEN; it would never reread the fake vault" >&2; exit 1
fi
.venv/bin/python "$SKILL_DIR/mcp_client.py" doctor \
  --url "http://127.0.0.1:${MCP_PORT}/mcp" --evidence "$EVIDENCE"
.venv/bin/python "$SKILL_DIR/mcp_client.py" doctor \
  --url "http://127.0.0.1:${ROT_PORT}/mcp" --evidence "$EVIDENCE" --label rot
```

Pass is `doctor ok`, these names, and `upstream_requests_added 0`, printed twice (main, then rotation):

```
scan_universe
get_thesis
get_fit_score
get_crash_risk
get_earnings_analysis
get_geopolitical
get_iv
```

`tools.json` and `tools-rot.json` hold the same lists. Any extra tool, any missing tool, or a name containing `order`, `buy`, or `sell` fails the doctor. Do not curl `/mcp`; streamable HTTP needs this client. Run Doctor again after any failed drive.

## Drive

Selectors are the tool name and its JSON arguments. There is no page to click. Drive one tool per command, serially. Every feature, with its exact commands and pass conditions, is in [features/README.md](features/README.md). The smoke call is `get_crash_risk` on the main server (no arguments, one GET, empty query):

```bash
set -euo pipefail
. .cursor/skills/verify-jarvis-trading-mcp/vars.sh
.venv/bin/python "$SKILL_DIR/mcp_client.py" drive \
  --url "http://127.0.0.1:${MCP_PORT}/mcp" --evidence "$EVIDENCE" --tool get_crash_risk
```

Pass prints `"ok": true`, `"upstream_path": "/api/macro/crash-risk"`, `"rows_matched": true`, `"paper": true`, `"orders_placed": 0`, and one new access-log row with status 200 and `token_last4` `aper`.

`mcp_client.py drive` options:

| Option | Meaning |
| --- | --- |
| `--tool`, `--args` | Tool name and JSON arguments |
| `--label L` | Write `call-<tool>-L.json` and `side-effects-L.json` instead of overwriting the unlabeled files |
| `--expect-rows JSON` | Exact list of `{"status", "token_last4"}` the paper backend must log for this call, in order. Default `[{"status":200,"token_last4":"aper"}]` |
| `--expect-error TEXT` | The tool must return an error containing `TEXT` (paper body checks are skipped) |
| `--kv-log F --expect-kv-reads N` | The fake Key Vault must log exactly `N` reads during this call |

`mcp_client.py leakcheck --evidence DIR --token VALUE ...` fails if any full token value appears in any file under `DIR`, and writes `leakcheck.json`. Do not pass `paper`: it is also a fixture key in every body.

## Repo checks

- Doctor lists the seven tools on both servers.
- Drive every feature in [features/README.md](features/README.md) through `mcp_client.py`, then run `signin_matrix.py`. No live orders: the server never places one, the paper process rejects non-GET methods and unknown paths, and the client refuses a non-loopback MCP URL.
- Run the unit tests (last section).

## Evidence

Saved under `$EVIDENCE`:

| File | What it shows |
| --- | --- |
| `paper.log`, `server.log`, `rot-server.log` | Readiness of each process. Server logs must not contain a full token |
| `paper-access.jsonl` | Every upstream request: method, path, query, status, `token_last4` only |
| `fake-kv-reads.jsonl` | Every fake Key Vault read: secret name and `value_last4` only |
| `tools.json`, `tools-rot.json` | Doctor tool lists |
| `call-<tool>[-label].json` | Tool result or tool error text |
| `side-effects[-label].json` | The new upstream rows, the expected rows, Key Vault reads, and pass flags |
| `leakcheck.json` | Files scanned and any full-token hits (must be none) |
| `signin-matrix.json`, `signin-<case>.log` | One startup per sign-in combination: exit code, refusal line, traceback flag |
| `paper.pid`, `mcp.pid`, `rot.pid` | Processes Cleanup is allowed to kill |

Proof standards:

- The user path is real: FastMCP `Client` → `friend_mcp.server` → `httpx.get` → paper backend. The paper process sits on the research-API boundary and `fake_kv/` sits on the Key Vault boundary. Those are the only mocks. Never call `_refresh_backend_token` or other internals directly; the tests already do that.
- Capture the call and the resulting upstream rows, not only the tool result. A 401 retry proof needs the two access-log rows (old last4 then new last4) and the one fake Key Vault read.
- There is no dry-run mode. Overriding `JARVIS_TRADING_API` still sends the GET, still attaches `X-API-Token`, still parses JSON, and still counts against the in-process rate limit (`JARVIS_TRADING_MAX_CALLS_PER_MIN`, default 30 per 60s; a 401 retry takes its own slot). It does not call the deployed API, so `get_thesis` does not spend a model call. Confirm the skip from `paper-access.jsonl`, not from the variable name.
- No screenshot: there is no UI. Do not send mail, chat, or orders.
- `server.log` and `rot-server.log` show `ERROR:mcp.server.streamable_http:Error in standalone SSE writer` with an `anyio.ClosedResourceError` traceback after each client session closes (mcp 1.29.0). It is library noise on session teardown, not a failed call. Judge calls by `side-effects*.json`.

## Cleanup

Kills only the processes in the pid files, removes `$SCRATCH` (token files), and keeps `$EVIDENCE`.

```bash
set -uo pipefail
. .cursor/skills/verify-jarvis-trading-mcp/vars.sh
for p in mcp rot paper; do
  [ -s "$EVIDENCE/$p.pid" ] && kill "$(cat "$EVIDENCE/$p.pid")" 2>/dev/null
done
for _ in $(seq 1 40); do
  alive=0
  for p in mcp rot paper; do
    [ -s "$EVIDENCE/$p.pid" ] && kill -0 "$(cat "$EVIDENCE/$p.pid")" 2>/dev/null && alive=1
  done
  [ "$alive" = 0 ] && break
  sleep 0.1
done
status=0
for p in mcp rot paper; do
  if [ -s "$EVIDENCE/$p.pid" ] && kill -0 "$(cat "$EVIDENCE/$p.pid")" 2>/dev/null; then
    echo "$p still running (pid $(cat "$EVIDENCE/$p.pid"))" >&2; status=1
  fi
done
case "$SCRATCH" in /tmp/verify-jarvis-trading-mcp-scratch-*) rm -rf "$SCRATCH" ;; esac
for f in tools.json call-get_crash_risk.json side-effects.json paper-access.jsonl; do
  test -s "$EVIDENCE/$f" || { echo "missing evidence $f" >&2; status=1; }
done
[ "$status" = 0 ] && echo "evidence kept in $EVIDENCE"
exit "$status"
```

## Tests, lint, and build

No GitHub Actions workflow, Makefile, or linter is configured. CI runs no test, lint, or build command. Before a PR, compile the package and run the unit tests with the venv from Launch. The tests use in-memory fakes for Key Vault and the trading API and a stub `az`, so they make no network or Azure calls. They leave `.test-fastmcp-home/` behind, which is gitignored.

```bash
set -euo pipefail
.venv/bin/python -m compileall -q friend_mcp
.venv/bin/python -c "import friend_mcp.server"
.venv/bin/python -m unittest discover -s tests -t . -v
```

The unit tests call the token helpers in-process. They do not replace the live journeys in [token-reread](features/token-reread.md) and [signin-guard](features/signin-guard.md), which go through a real server process.
