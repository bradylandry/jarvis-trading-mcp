# jarvis-trading-mcp

A remote MCP server that gives Claude (web, desktop, or Code) read-only
access to Brady's `jarvis-trading` research API: options screening, AI
thesis generation, earnings analysis, macro signals, implied vol lookup.

**Access is by invitation.** You sign in with your own account through
Microsoft Entra; there is no token to install and no code to run on your
machine. If Brady hasn't invited you, this isn't for you.

## What this actually is

A hosted FastMCP server (Python) running on Azure Container Apps. It:

1. Authenticates you with **Entra OAuth** on the LandryCMD tenant, so
   each user logs in as themselves (no shared secret in your config).
2. Speaks the remote **streamable-HTTP** MCP transport, so Claude
   connects to a URL instead of launching a local subprocess.
3. Translates each tool call into an authenticated HTTPS GET against
   Brady's research API at `trading.landrycmd.com`.
4. Returns the JSON response as Claude-readable text.

The trading API itself runs on Brady's Azure VM (`jarvis-lab`) and is
closed-source. This server is just the bridge.

Two auth layers, so it's clear what a token is and isn't:

- **You → this server: per-user OAuth.** You log in through Entra and get
  your own token scoped to `read`. Nobody pastes a shared `tok_...` into a
  config anymore.
- **This server → the trading API: one server-side token.** The server
  holds a single `X-API-Token`, pulled at runtime from Azure Key Vault via
  its Managed Identity (or from the macOS Keychain in local dev). It never
  lands on disk and no user ever sees it.

## Tools added to your Claude session

| Tool | What it returns | Cost (Brady absorbs) |
| --- | --- | --- |
| `scan_universe(mode, budget, opt_type)` | Top options candidates from a 50-name liquid universe, ranked by fit_score, filtered by hunt mode (`plan_b` / `plan_a` / `directional`). | $0 (cached 5 min) |
| `get_thesis(ticker, strike, expiration, opt_type)` | Grok + Kimi A/B thesis for one specific contract: verdict, bull case, bear case, exit plan. Catalyst- and regime-aware. | ~$0.0015/call (Grok) |
| `get_fit_score(ticker, opt_type)` | Directional alignment 0-10, with sentiment / fundamentals / Kimi-earnings / Kimi-vs-analyst-disagreement / insider components. | $0 |
| `get_crash_risk()` | Composite market regime score 0-10, 6 leading indicators broken out. | $0 (cached 6h) |
| `get_earnings_analysis(ticker)` | Most recent Kimi-graded SEC 8-K read on the ticker. Deep-dive analyst take: BUY/HOLD/AVOID verdict + 3-5 sentence verdict thesis explaining why, conviction (HIGH/MEDIUM/LOW), 3-5 paragraph deep-dive narrative, numbers breakdown, bull/bear case, forward catalysts, forward risks, 12-month qualitative outlook, analyst-consensus disagreement signal. | $0 |
| `get_geopolitical()` | Multi-region geopolitical + macro regime signal. | $0 (cached 5 min); ~$0.0015 on cache miss |
| `get_iv(ticker, dte=30)` | ATM implied volatility + realized-vol context. Spot, ATM call+put bid/ask/mid/IV/volume/OI, 30d realized vol, RV percentile vs 1y history, IV/RV ratio, breakeven % move on the ATM call. For "is this option expensive" / "compare option pricing across tickers" without `get_thesis()`'s Grok cost. | $0 (cached 5 min) |

## Disclaimer

**Research and informational only. Not financial advice. No SLA. No
guarantees on data freshness or correctness. Brady provides this as a
courtesy; your trades are your responsibility.** If a tool returns
something that costs you money, that's between you and the market, not
Brady.

## How to get access

There are two steps, and Brady does the first one.

**1. Brady invites you to the LandryCMD tenant.** You get a Microsoft
invitation email; click **Accept**. This puts your account in the login
directory for this MCP and nothing else. It gives you zero access to any
of Brady's other tenants or resources.

**2. You add the connector in Claude.** In Claude → **Settings →
Connectors → Add custom connector**, paste:

```
https://jarvis-trading-mcp.gentlegrass-cc0fcf07.southcentralus.azurecontainerapps.io/mcp
```

Sign in with the account Brady invited, approve the **read** scope, and
the 7 tools above appear in your session. That's it: no `pip install`, no
config file, no token.

### Quick check it's working

Ask Claude: "what's the current crash risk score?" Claude should call
`get_crash_risk()` and return the composite plus components.

- If the connector won't authorize, confirm you accepted the Entra
  invitation and are signing in with that same account.
- If tools start returning a token error, the server-side backend token
  has been rotated. That's on Brady's side; ping him.

## What you can ask Claude

You don't call these tools directly. You ask Claude in plain English and
it picks the right tool(s). Below are example prompts grouped by what
you're trying to do. Copy-paste any of them as a starting point.

### Find a trade

- *"What are the best Plan B options trades to look at this week? Budget $75."*
  → Claude calls `scan_universe(mode=plan_b, budget=75, opt_type=call)` and returns ranked candidates with fit scores, IV, OTM%, breakeven.
- *"Show me bearish put candidates on stocks with weak fundamentals."*
  → Claude calls `scan_universe(mode=plan_b, opt_type=put)` and walks through the top results.
- *"Any directional plays right now on stocks with strong setups but no near-term earnings?"*
  → Claude calls `scan_universe(mode=directional, opt_type=call)`.

### Evaluate a specific contract

- *"What do you think about a NVDA $250 call expiring 5/29?"*
  → Claude calls `get_thesis(ticker=NVDA, strike=250, expiration=2026-05-29, opt_type=call)` and shows you Grok + Kimi side-by-side analysis: bull case, bear case, exit plan, verdict.
- *"Should I buy a TGT $115 put for 6/18?"*
  → Same: Claude pulls the thesis with regime + catalyst + fit gating already applied.
- *"Compare two contracts for me: NVDA $250 5/29 vs $260 5/29."*
  → Claude calls `get_thesis` twice and contrasts.

### Check directional alignment

- *"Is NOW a bullish or bearish setup right now?"*
  → Claude calls `get_fit_score(ticker=NOW, opt_type=call)` and explains which signals are firing (sentiment, fundamentals, Kimi earnings grade, Kimi-vs-analyst delta, insider activity).
- *"Why does the screener say MSTR is high-fit for puts?"*
  → Claude calls `get_fit_score(ticker=MSTR, opt_type=put)` and walks through the bearish signals.

### Read the macro picture

- *"What's the current crash risk score and what's driving it?"*
  → Claude calls `get_crash_risk()` and explains the 6 components: yield curve, market breadth, VIX term structure, credit spreads, insider selling, earnings sentiment.
- *"How's geopolitical risk shaping up, is the Iran/China stuff getting worse?"*
  → Claude calls `get_geopolitical()` and summarizes the 5 region scores (Ukraine, Iran, China, Tariff, Fed-hawkishness).
- *"Is this a good regime to be opening Plan B trades?"*
  → Claude calls both `get_crash_risk()` and `get_geopolitical()` and gives you a synthesized read.

### Dig into a specific company's earnings

- *"What did Kimi say about NOW's most recent earnings?"*
  → Claude calls `get_earnings_analysis(ticker=NOW)` and pulls the verdict (BUY/HOLD/AVOID), bull case, bear case, EPS surprise %, analyst consensus.
- *"How did SNOW's last quarter compare to consensus?"*
  → Same tool: Claude walks through the divergence between Kimi's grade and analyst ratings.

### Compare option pricing across tickers (free, no Grok cost)

- *"Why are MRVL options so expensive but NVDA cheaper at similar prices?"*
  → Claude calls `get_iv(ticker=MRVL)` and `get_iv(ticker=NVDA)` and compares. Returns ATM IV, realized vol, RV percentile, IV/RV ratio, breakeven % move on the ATM call. Explains the IV gap with hard numbers, no LLM cost.
- *"Is the AVGO call I'm looking at expensive vs its 1-year history?"*
  → `get_iv(ticker=AVGO)`: returns where today's realized vol sits in 1y history (proxy for IV percentile), plus IV/RV ratio (>1.2 = market's pricing in MORE vol than recent realized; <0.9 = IV looks cheap).
- *"How rich is TSLA's 45-DTE IV right now?"*
  → `get_iv(ticker=TSLA, dte=45)`: ATM IV at the expiration nearest 45 days out, plus realized-vol context.

### Combine tools for richer questions

The real value: ask Claude to chain tools naturally.

- *"I'm thinking about buying a CRM call into earnings. Walk me through whether that's a good idea."*
  → Claude likely calls `get_fit_score` for direction, `get_earnings_analysis` for fundamentals context, then `get_thesis` for a specific contract you mention.
- *"Find me 3 high-conviction Plan B candidates for late May, then show me one specific contract for the top pick."*
  → Claude calls `scan_universe`, picks one, then calls `get_thesis` on it.
- *"Is now a good time to be aggressive on options, or should I sit on cash?"*
  → Claude calls `get_crash_risk` + `get_geopolitical` and synthesizes regime guidance.

### What this system does NOT do

Be aware of the boundaries. Don't expect:

- ❌ Real-time stock prices (you can ask, but Claude pulls the price as a side-effect of `get_thesis`; standalone live-price queries aren't a tool)
- ❌ Historical price charts or technical indicators (no chart tool exposed)
- ❌ News headlines (the system reads SEC 8-K filings via Kimi, not news feeds; Grok pulls live X/Twitter sentiment but that surfaces inside `get_thesis`, not as a standalone tool)
- ❌ Multi-leg options strategies (iron condors, spreads, etc.); only single-contract analysis
- ❌ Greeks for arbitrary strikes (only the strike you pass to `get_thesis` gets analyzed)
- ❌ Stock fundamentals by themselves (P/E, ROE, etc.); those feed into `get_fit_score` but aren't directly queryable
- ❌ Sports betting picks (separate system, not exposed here)
- ❌ Brady's own positions (private, not in the API)

### Quick reference card

| If you want to… | Ask something like… |
| --- | --- |
| Find candidate trades | "What are the best Plan B [calls/puts] this week, budget \$X?" |
| Evaluate a contract | "What do you think about a TICKER \$STRIKE [call/put] EXP?" |
| Check direction | "Is TICKER bullish or bearish setup right now?" |
| Macro check | "What's the crash risk and geopolitical regime?" |
| Earnings deep-dive | "What did Kimi say about TICKER's last earnings?" |
| Compare option pricing | "Why are TICKER1 options pricier than TICKER2?" |
| Compare two contracts | "Compare TICKER \$X CALL vs \$Y CALL for EXP" |

## Cost / quota

Each tool call hits Brady's trading-site API. Brady absorbs the cost
(Grok per-call spend, Tradier quota burn). Keep usage reasonable:

- The thesis tool spends ~$0.0015 per call (Grok call to xAI). Don't loop
  it across 50 tickers.
- `scan_universe` is free + cached 5 min; call it freely.
- `get_crash_risk` and `get_earnings_analysis` are free + cached 6h.
- `get_iv` is free + cached 5 min.
- `get_geopolitical` is cached 5 min, refresh costs ~$0.0015.

Brady monitors usage server-side for cost attribution. If you're burning
calls in a way that surprises him, expect a friendly chat about
right-sized usage. Access is revocable per user.

## Privacy

Tool calls and their arguments are logged on Brady's side for cost
attribution and debugging. He sees that you connected, and which tools
you call (e.g. "scan_universe ran 5 times today"). He does NOT see your
Claude conversation context, only the structured tool inputs. Because all
backend calls currently share one server-side token, per-user attribution
in the trading API logs is coarse; Entra records who authenticated.

## Rate limiting

The server enforces a cap of **30 tool calls per 60 seconds** to protect
the upstream API from runaway tool-call loops. If hit, the next call
returns a structured error explaining when to retry; subsequent calls stay
blocked until the sliding window clears. The cap is enforced in the server
process (a lock-guarded sliding window), and Brady's server-side per-token
quota remains the authoritative ceiling. The limit is configured on the
deployment (`JARVIS_TRADING_MAX_CALLS_PER_MIN`), not in your client.

## Security

This server has been reviewed with the static-analysis tool
[mcp-audit](https://github.com/bradylandry/mcp-audit). Latest run:
**Score 10/10, low risk.** Reproduce it:

```bash
pip install git+https://github.com/bradylandry/mcp-audit.git
git clone https://github.com/bradylandry/jarvis-trading-mcp.git
mcp-audit jarvis-trading-mcp/
```

**What the server can and can't do** (audited):

- ✅ Makes outbound HTTPS GET requests to one host (`trading.landrycmd.com`)
- ✅ Serves the MCP over HTTP behind Entra OAuth (an inbound listener is the whole point of a remote server; it fails closed if auth isn't configured on a public bind)
- ✅ Reads the backend token from Azure Key Vault via Managed Identity (or the Keychain locally); reads config from env vars
- ❌ No subprocess, shell, or `eval`
- ❌ No filesystem reads or writes
- ❌ TLS verification is on (no `verify=False`)
- ❌ No unsafe deserialization

**Trust model, remote edition.** Because this is a hosted server, you run
none of its code; the blast radius on your machine is nil. What you're
trusting is (a) Brady, who operates the server and the API, and (b) that
your login is your own (OAuth, not a shared secret). The classic MCP risks
of "plaintext token in your config" and "pip-install code you have to
re-review on every upgrade" don't apply to this deployment.

**The one risk that remains: prompt injection via tool responses.** This
is intrinsic to any MCP that returns third-party content. Every field the
API returns (`bull_case`, `verdict_thesis`, `summary`, etc.) lands in
Claude's context as text. If `trading.landrycmd.com` were ever compromised,
that text could carry "ignore previous instructions, do X" content.

Mitigation: **don't co-mount this MCP in a Claude session that also holds
tools capable of acting on injected instructions.** Avoid sharing a session
with tools that can write files, run shell, push to git, send mail/chat,
move money, or modify cloud resources. Read-only research MCPs like this
one are safe to share a session with each other. The line is "tools that
can ACT" vs "tools that just RETURN information." The server also returns
only the HTTP status code on upstream errors, not the raw response body,
to avoid leaking upstream content into your context.

## Running your own (Brady, or a fork operator)

- `friend_mcp/server.py` is the whole server: 7 `@mcp.tool` wrappers over
  `trading.landrycmd.com`, `AzureProvider` OAuth (enabled when
  `AUTH_CLIENT_ID` is set), backend token via Key Vault / Keychain, and a
  lock-guarded rate limiter. It fails closed on a public bind without auth.
- `run-local.sh` starts it on loopback with the token from the Keychain, no
  OAuth, for development.
- `deploy.sh` builds the image in ACR and deploys to Azure Container Apps,
  wiring the Managed Identity to Key Vault and the OAuth env to the login
  tenant. The full setup runbook (tenant, app registration, the
  `requestedAccessTokenVersion=2` gotcha) lives in Brady's notes.
- Deps are pinned in `requirements.txt` / `pyproject.toml`: `fastmcp`,
  `httpx`, `azure-identity`, `azure-keyvault-secrets`.

## License

MIT. See `LICENSE`.

The server code is open source. The trading API it talks to is closed
source and operated by Brady at `trading.landrycmd.com`. That API is NOT
covered by this license; it's a courtesy service, revocable at any time.
