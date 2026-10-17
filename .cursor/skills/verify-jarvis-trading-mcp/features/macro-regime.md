# Macro regime

## Sub-features

- `get_crash_risk`: composite `score` plus `yield_curve`, `breadth`, `vix_term_structure`, `credit_spreads`, `insider_selling`, `earnings_sentiment`. No arguments.
- `get_geopolitical`: region scores `ukraine`, `iran`, `china_taiwan`, `tariff`, `fed_hawkishness`. No arguments. Upstream path is `/api/macro/political`.

## How to get to it (user POV)

"What's the current crash risk score?" is the README's quick check. Claude calls `get_crash_risk`. "How's geopolitical risk shaping up?" calls `get_geopolitical`. A regime question often calls both.

## Driving it with the FastMCP client

`get_crash_risk` is the skill's proof call:

```bash
.venv/bin/python .cursor/skills/verify-jarvis-trading-mcp/mcp_client.py drive \
  --url "http://127.0.0.1:${MCP_PORT}/mcp" \
  --evidence "$EVIDENCE" \
  --tool get_crash_risk
```

Geopolitical:

```bash
.venv/bin/python .cursor/skills/verify-jarvis-trading-mcp/mcp_client.py drive \
  --url "http://127.0.0.1:${MCP_PORT}/mcp" \
  --evidence "$EVIDENCE" \
  --tool get_geopolitical
```

Pass for crash risk: one `GET /api/macro/crash-risk` with an empty query, `score` 3.5, `orders_placed` 0. Pass for geopolitical: one `GET /api/macro/political` with an empty query. Each drive rewrites `side-effects.json`; per-tool bodies stay in `call-<tool>.json`.

## Gotchas

- Paper scores are fixtures. Do not quote them as a market read.
- On the deployed API, crash risk is cached about six hours and geopolitical about five minutes. Paper does not cache.
- With `JARVIS_TRADING_MAX_CALLS_PER_MIN=1`, the second call raises `client-side rate limit hit (1/60s)` and does not record another 200.
