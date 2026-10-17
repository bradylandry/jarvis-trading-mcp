---
name: verify-jarvis-trading-mcp
description: Verify jarvis-trading-mcp, a streamable-HTTP MCP server with seven read-only research tools, against a loopback paper backend. Use before opening or updating a PR.
---

# Verify jarvis-trading-mcp

Users reach this app as an MCP connector (Claude or any streamable-HTTP client). There is no web UI. `friend_mcp/server.py` exposes seven tools and turns each call into one authenticated GET. Locally the process is `python -m friend_mcp.server` on `HOST`/`PORT` (default port 8080), path `/mcp`.

`run-local.sh` is not the verify path. It shells out to macOS `security` and leaves `JARVIS_TRADING_API` pointed at the deployed research API. This skill starts a paper backend instead. The server has no dry-run flag: a non-loopback `JARVIS_TRADING_API` is a live call.

Two processes can run side by side. Give each pair its own `PAPER_PORT`, `MCP_PORT`, and `EVIDENCE` directory. The rate limiter and token cache are in-process, so they do not collide. `HOST` must stay `127.0.0.1` (a public bind without `AUTH_CLIENT_ID` exits).

Run from the repository root. Evidence goes to `/tmp/verify-jarvis-trading-mcp` and is not deleted by Cleanup.

## Launch

```bash
set -euo pipefail
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
unset AUTH_CLIENT_ID AUTH_CLIENT_SECRET AUTH_TENANT_ID PUBLIC_BASE_URL \
  KEY_VAULT_URL JARVIS_TOKEN_SECRET_NAME ALLOW_UNAUTHENTICATED
EVIDENCE=/tmp/verify-jarvis-trading-mcp
PAPER_PORT=8765
MCP_PORT=8080
API_URL="http://127.0.0.1:${PAPER_PORT}"
case "$API_URL" in
  http://127.0.0.1:[0-9]*) ;;
  *) echo "refusing non-loopback JARVIS_TRADING_API" >&2; exit 1 ;;
esac
rm -rf "$EVIDENCE"
mkdir -p "$EVIDENCE"
PYTHONUNBUFFERED=1 .venv/bin/python .cursor/skills/verify-jarvis-trading-mcp/paper_backend.py \
  --host 127.0.0.1 --port "$PAPER_PORT" \
  --access-log "$EVIDENCE/paper-access.jsonl" \
  > "$EVIDENCE/paper.log" 2>&1 &
echo $! > "$EVIDENCE/paper.pid"
for _ in $(seq 1 60); do
  if grep -q "paper backend ready http://127.0.0.1:${PAPER_PORT}" "$EVIDENCE/paper.log" 2>/dev/null; then
    break
  fi
  sleep 0.25
done
grep -q "paper backend ready http://127.0.0.1:${PAPER_PORT}" "$EVIDENCE/paper.log"
PYTHONUNBUFFERED=1 \
JARVIS_TRADING_TOKEN=paper \
JARVIS_TRADING_API="$API_URL" \
HOST=127.0.0.1 \
PORT="$MCP_PORT" \
.venv/bin/python -m friend_mcp.server \
  > "$EVIDENCE/server.log" 2>&1 &
echo $! > "$EVIDENCE/mcp.pid"
for _ in $(seq 1 60); do
  if grep -q "Uvicorn running on http://127.0.0.1:${MCP_PORT}" "$EVIDENCE/server.log" 2>/dev/null; then
    break
  fi
  sleep 0.25
done
grep -q "Uvicorn running on http://127.0.0.1:${MCP_PORT}" "$EVIDENCE/server.log"
echo "ready paper=${PAPER_PORT} mcp=${MCP_PORT}"
```

Readiness is two lines: `paper backend ready http://127.0.0.1:8765` in `paper.log`, then `Uvicorn running on http://127.0.0.1:8080` in `server.log`. The FastMCP "Starting MCP server" line is wrapped by the rich logger, so do not grep that sentence.

Teardown is the Cleanup block. Leave both processes up until Doctor, Drive, and Evidence have been written.

## Doctor

Read-only usability check. Lists tools over MCP. It must not add a line to the paper access log.

```bash
set -euo pipefail
EVIDENCE=/tmp/verify-jarvis-trading-mcp
MCP_PORT=8080
.venv/bin/python .cursor/skills/verify-jarvis-trading-mcp/mcp_client.py doctor \
  --url "http://127.0.0.1:${MCP_PORT}/mcp" \
  --evidence "$EVIDENCE"
```

Pass looks like `doctor ok`, then these names, then `upstream_requests_added 0`:

```
scan_universe
get_thesis
get_fit_score
get_crash_risk
get_earnings_analysis
get_geopolitical
get_iv
```

`tools.json` is the same list. Any extra tool, any missing tool, or a name containing `order`, `buy`, or `sell` fails the doctor. Do not curl `/mcp`; streamable HTTP needs this client.

## Drive

Selectors are the tool name and its JSON arguments. There is no page to click. Drive one tool per command. The proof call is `get_crash_risk` (no arguments, one GET, empty query). Per-tool commands live in `features/`.

```bash
set -euo pipefail
EVIDENCE=/tmp/verify-jarvis-trading-mcp
MCP_PORT=8080
.venv/bin/python .cursor/skills/verify-jarvis-trading-mcp/mcp_client.py drive \
  --url "http://127.0.0.1:${MCP_PORT}/mcp" \
  --evidence "$EVIDENCE" \
  --tool get_crash_risk
```

Pass prints `"ok": true`, `"upstream_path": "/api/macro/crash-risk"`, `"all_get": true`, `"orders_placed": 0`, `"paper": true`, and one new access-log row whose `token_last4` is `aper`.

## Repo checks

- List the MCP tools with Doctor. Expect the seven names above.
- Call one tool with Drive through `mcp_client.py` against the paper backend. No live orders. This server never places one; the paper process rejects non-GET methods and unknown paths, and the client refuses a non-loopback MCP URL.

## Evidence

Saved under `/tmp/verify-jarvis-trading-mcp`:

| File | What it shows |
| --- | --- |
| `paper.log` | Paper process readiness |
| `server.log` | Uvicorn readiness and the MCP banner |
| `paper-access.jsonl` | Every upstream request: method, path, query, status, `token_last4` only |
| `tools.json` | Doctor tool list |
| `call-get_crash_risk.json` | Tool result (`paper`, `score`, `components`, `orders_placed`) |
| `side-effects.json` | The single new GET and the pass flags |
| `paper.pid`, `mcp.pid` | Processes Cleanup is allowed to kill |

The user path is real: FastMCP `Client` → `friend_mcp.server` → `httpx.get` → paper backend. The paper process is the only mock, and it sits on the research-API boundary.

There is no dry-run mode. Overriding `JARVIS_TRADING_API` still sends the GET, still attaches `X-API-Token`, still parses JSON, and still counts against the in-process rate limit (`JARVIS_TRADING_MAX_CALLS_PER_MIN`, default 30 per 60s). It does not call the deployed API, so `get_thesis` does not spend a model call. Confirm the skip by reading `paper-access.jsonl`: one `GET`, status 200, `token_last4` `aper`, and `orders_placed` 0 in the call file. A second call after the cap is hit raises `client-side rate limit hit (N/60s)` and does not add a successful upstream row.

No screenshot: there is no UI. Do not send mail, chat, or orders.

## Cleanup

Kills only the two pid files. Does not remove `EVIDENCE`.

```bash
set -euo pipefail
EVIDENCE=/tmp/verify-jarvis-trading-mcp
kill "$(cat "$EVIDENCE/mcp.pid")" "$(cat "$EVIDENCE/paper.pid")"
for _ in $(seq 1 20); do
  if ! kill -0 "$(cat "$EVIDENCE/mcp.pid")" 2>/dev/null \
    && ! kill -0 "$(cat "$EVIDENCE/paper.pid")" 2>/dev/null; then
    break
  fi
  sleep 0.1
done
if kill -0 "$(cat "$EVIDENCE/mcp.pid")" 2>/dev/null; then
  echo "mcp still running" >&2
  exit 1
fi
if kill -0 "$(cat "$EVIDENCE/paper.pid")" 2>/dev/null; then
  echo "paper still running" >&2
  exit 1
fi
test -s "$EVIDENCE/tools.json"
test -s "$EVIDENCE/call-get_crash_risk.json"
test -s "$EVIDENCE/side-effects.json"
test -s "$EVIDENCE/paper-access.jsonl"
echo "evidence kept in $EVIDENCE"
```

## Tests, lint, and build

No GitHub Actions workflow, Makefile, pytest suite, or linter is configured. CI runs no test, lint, or build command. Before a PR, compile the package with the venv from Launch:

```bash
set -euo pipefail
.venv/bin/python -m compileall -q friend_mcp
.venv/bin/python -c "import friend_mcp.server"
```
