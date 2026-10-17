# Evaluate one contract

## Sub-features

- Contract identity: `ticker`, `strike`, `expiration` (`YYYY-MM-DD`), `opt_type` (`call` or `put`).
- Returned fields on the paper fixture: `verdict`, `bull_case`, `bear_case`, `exit_plan`.
- The live tool is the one that spends a model call. The paper path does not.

## How to get to it (user POV)

The user asks about a specific contract, for example "What do you think about a NVDA $250 call expiring 5/29?" Claude calls `get_thesis` with `ticker=NVDA`, `strike=250`, `expiration=2026-05-29`, `opt_type=call`.

## Driving it with the FastMCP client

```bash
.venv/bin/python .cursor/skills/verify-jarvis-trading-mcp/mcp_client.py drive \
  --url "http://127.0.0.1:${MCP_PORT}/mcp" \
  --evidence "$EVIDENCE" \
  --tool get_thesis \
  --args '{"ticker":"nvda","strike":250,"expiration":"2026-05-29","opt_type":"call"}'
```

Pass: one `GET /api/options/thesis` with query `ticker=NVDA`, `strike=250.0`, `expiration=2026-05-29`, `type=call`.

## Gotchas

- Ticker is uppercased in `friend_mcp/server.py` before the GET. `opt_type` goes out as `type`.
- There is no dry-run switch. If `JARVIS_TRADING_API` is not the paper backend, this GET hits the deployed API and spends the thesis model call. The access log is the proof it stayed on paper.
- The server does not validate the expiration string. A bad date is the upstream's problem; paper echoes it.
