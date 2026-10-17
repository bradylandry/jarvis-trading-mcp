# Scan the universe

## Sub-features

- Hunt mode: `plan_b`, `plan_a`, or `directional` (default `plan_b`).
- Premium budget in dollars (default `75`).
- `opt_type`: `call` or `put` (default `call`).
- Ranked candidates. The paper backend returns one `PAPER` row with `fit_score` 7.0.

## How to get to it (user POV)

The user asks Claude in plain English, for example "What are the best Plan B options trades to look at this week? Budget $75." Claude calls `scan_universe`. There is no screen of our own.

## Driving it with the FastMCP client

```bash
.venv/bin/python .cursor/skills/verify-jarvis-trading-mcp/mcp_client.py drive \
  --url "http://127.0.0.1:${MCP_PORT}/mcp" \
  --evidence "$EVIDENCE" \
  --tool scan_universe \
  --args '{"mode":"plan_b","budget":75,"opt_type":"call"}'
```

Pass: one `GET /api/options/scan/universe` with query `mode=plan_b`, `budget=75.0`, `type=call`. `call-scan_universe.json` has `data` as a list; `structured_content.result` is that same list. `paper` is true and `orders_placed` is 0.

## Gotchas

- The tool argument `opt_type` is sent as the query key `type`. `budget` is stringified (`75.0`).
- A list result is not a failure. Dict-returning tools put the object on `data` directly; this one wraps it.
- On the deployed API the scan is cached about five minutes. The paper backend does not cache.
