# Directional fit

## Sub-features

- `ticker` (required) and `opt_type` (`call` default, or `put`).
- Paper fixture returns `fit_score` 6.0 for the echoed ticker.
- Live score is documented as 0–10 with sentiment, fundamentals, earnings, analyst-disagreement, and insider components. Those components are upstream fields; paper does not invent them.

## How to get to it (user POV)

The user asks "Is NOW a bullish or bearish setup right now?" Claude calls `get_fit_score(ticker=NOW, opt_type=call)`. "Why does the screener say MSTR is high-fit for puts?" uses `opt_type=put`.

## Driving it with the FastMCP client

```bash
.venv/bin/python .cursor/skills/verify-jarvis-trading-mcp/mcp_client.py drive \
  --url "http://127.0.0.1:${MCP_PORT}/mcp" \
  --evidence "$EVIDENCE" \
  --tool get_fit_score \
  --args '{"ticker":"now","opt_type":"put"}'
```

Pass: one `GET /api/screener` whose query is only `tickers=NOW`.

## Gotchas

- `opt_type` is accepted and then dropped. The upstream query is `tickers` (plural), uppercased. A paper call with `opt_type=put` still requests `tickers=NOW` and nothing else.
- The tool does not send a directional side, so a put-vs-call difference cannot be verified from this process alone.
