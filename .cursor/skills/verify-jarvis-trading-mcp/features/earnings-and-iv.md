# Earnings and implied vol

## Sub-features

- `get_earnings_analysis(ticker)`: paper returns verdict `HOLD`, conviction `LOW`, and a fixture thesis. Upstream path `/api/macro/earnings-analyses`.
- `get_iv(ticker, dte=30)`: paper returns `atm_iv`, `realized_vol_30d`, and `iv_rv_ratio`. Upstream path `/api/options/iv`.

## How to get to it (user POV)

"What did Kimi say about NOW's most recent earnings?" calls `get_earnings_analysis`. "Is the AVGO call I'm looking at expensive vs its 1-year history?" calls `get_iv`. "How rich is TSLA's 45-DTE IV?" passes `dte=45`.

## Driving it with the FastMCP client

```bash
.venv/bin/python .cursor/skills/verify-jarvis-trading-mcp/mcp_client.py drive \
  --url "http://127.0.0.1:${MCP_PORT}/mcp" \
  --evidence "$EVIDENCE" \
  --tool get_earnings_analysis \
  --args '{"ticker":"snow"}'
```

```bash
.venv/bin/python .cursor/skills/verify-jarvis-trading-mcp/mcp_client.py drive \
  --url "http://127.0.0.1:${MCP_PORT}/mcp" \
  --evidence "$EVIDENCE" \
  --tool get_iv \
  --args '{"ticker":"avgo","dte":45}'
```

Pass: `GET /api/macro/earnings-analyses?ticker=SNOW`, then `GET /api/options/iv` with `ticker=AVGO` and `dte=45`.

## Gotchas

- Both tickers are uppercased on the wire. `dte` is sent as an integer string (`45`).
- A ticker the live service has never graded comes back empty. Paper always returns the HOLD fixture, so an empty-state check needs the deployed API and is out of scope here.
- Both tools are free on the deployed API (`get_iv` cached about five minutes). They are still real GETs; the access log should gain one row per drive.
