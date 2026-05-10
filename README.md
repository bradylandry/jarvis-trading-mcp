# jarvis-trading-mcp

An MCP server that gives Claude (Desktop or Code) read-only access to
Brady's `jarvis-trading` research API — options screening, AI thesis
generation, earnings analysis, macro signals, implied vol lookup.

**You need a token from Brady to use this.** If you don't have one,
this isn't for you.

## What this actually is

A small Python package (~250 lines, one runtime dependency: `requests`)
that:

1. Reads a token from your Claude config's `env` block
2. Implements stdio-based MCP JSON-RPC 2.0 so Claude can discover
   + invoke its tools
3. Translates each tool call into an authenticated HTTPS GET against
   Brady's research API at `trading.landrycmd.com`
4. Returns the JSON response as Claude-readable text

The trading API itself runs on Brady's GCP VM — closed-source. This
package is just the bridge.

## Trust model in one sentence

**If you trust Brady (the person operating the API) and pin to a
reviewed commit SHA, this MCP carries roughly the same risk as any
small `requests`-based Python package from a friend's GitHub.**

The full security audit is in `## Security audit` below — please
read it before installing.

## Tools added to your Claude session

| Tool | What it returns | Cost (Brady absorbs) |
| --- | --- | --- |
| `scan_universe(mode, budget, opt_type)` | Top options candidates from a 50-name liquid universe, ranked by fit_score, filtered by hunt mode (`plan_b` / `plan_a` / `directional`). | $0 (cached 5 min) |
| `get_thesis(ticker, strike, expiration, opt_type)` | Grok + Kimi A/B thesis for one specific contract — verdict, bull case, bear case, exit plan. Catalyst- and regime-aware. | ~$0.0015/call (Grok) |
| `get_fit_score(ticker, opt_type)` | Directional alignment 0-10, with sentiment / fundamentals / Kimi-earnings / Kimi-vs-analyst-disagreement / insider components. | $0 |
| `get_crash_risk()` | Composite market regime score 0-10, 6 leading indicators broken out. | $0 (cached 6h) |
| `get_earnings_analysis(ticker)` | Most recent Kimi-graded SEC 8-K read on the ticker. Deep-dive analyst take: BUY/HOLD/AVOID verdict + 3-5 sentence verdict thesis explaining why, conviction (HIGH/MEDIUM/LOW), 3-5 paragraph deep-dive narrative, numbers breakdown, bull/bear case, forward catalysts, forward risks, 12-month qualitative outlook, analyst-consensus disagreement signal. | $0 |
| `get_geopolitical()` | Multi-region geopolitical + macro regime signal. | $0 (cached 5 min); ~$0.0015 on cache miss |
| `get_iv(ticker, dte=30)` | ATM implied volatility + realized-vol context. Spot, ATM call+put bid/ask/mid/IV/volume/OI, 30d realized vol, RV percentile vs 1y history, IV/RV ratio, breakeven % move on the ATM call. For "is this option expensive" / "compare option pricing across tickers" without `get_thesis()`'s Grok cost. | $0 (cached 5 min) |

## Disclaimer

**Research and informational only. Not financial advice. No SLA. No
guarantees on data freshness or correctness. Brady provides this as a
courtesy — your trades are your responsibility.** If a tool returns
something that costs you money, that's between you and the market,
not Brady.

## Source code overview (audit-ready)

The whole package is two files:

- **`friend_mcp/server.py`** (~270 lines) — implements:
  - 7 Python functions, one per tool, that call `_api_get(path, params)`
  - `_api_get()` — sets the `X-API-Token` header, hits
    `https://trading.landrycmd.com<path>`, parses JSON, returns dict.
    On non-200 returns `{"error": "API returned status N..."}` —
    body content is intentionally NOT passed back to avoid leaking
    upstream content into Claude's context (added 2026-05-08 per
    security audit feedback).
  - `_send()`, `_handle()`, `main()` — minimal stdio JSON-RPC 2.0
    loop handling MCP `initialize`, `tools/list`, `tools/call`.
- **`friend_mcp/__init__.py`** — package marker, version constant.

That's all. No subprocess, no shell, no eval, no filesystem writes,
no inbound network, no third-party deps beyond `requests`.

## Install

**Recommended (pinned to a reviewed commit):**

```bash
pip install "git+https://github.com/bradylandry/jarvis-trading-mcp.git@<SHA>"
```

Replace `<SHA>` with the commit SHA Brady sent you (e.g. `d43c16e...`).
Pinning means future `pip install --upgrade` only takes a new version
when you re-pin — protects against any change to `master` between when
you reviewed the code and now. Re-pin and re-review on each upgrade.

**Quick (tracks `master`, no pin):**

```bash
pip install git+https://github.com/bradylandry/jarvis-trading-mcp.git
```

(Or clone + `pip install -e .` if you want to hack on it.)

## Configure Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or the equivalent on your platform:

```json
{
  "mcpServers": {
    "jarvis-trading": {
      "command": "jarvis-trading-mcp",
      "env": {
        "JARVIS_TRADING_TOKEN": "tok_xxxxxxxxxxxx"
      }
    }
  }
}
```

Replace `tok_xxx...` with the token Brady gave you. Restart Claude
Desktop. The 7 tools above should appear in your tool list.

## Configure Claude Code

Add to your project's `.claude/settings.json` (or your global
`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "jarvis-trading": {
      "command": "jarvis-trading-mcp",
      "env": {
        "JARVIS_TRADING_TOKEN": "tok_xxxxxxxxxxxx"
      }
    }
  }
}
```

## Quick check it's working

In a Claude session: ask "what's the current crash risk score?". Claude
should call `get_crash_risk()` and return the composite + components.

If you get `"JARVIS_TRADING_TOKEN env var is not set"` — your token
isn't being passed. Check the `env` block in your Claude config.

If you get `"Token rejected"` — your token has been revoked or rotated.
Ping Brady.

## What you can ask Claude

You don't call these tools directly — you ask Claude in plain English
and it picks the right tool(s). Below are example prompts grouped by
what you're trying to do. Copy-paste any of them as a starting point.

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
  → Same — Claude pulls the thesis with regime + catalyst + fit gating already applied.
- *"Compare two contracts for me — NVDA $250 5/29 vs $260 5/29."*
  → Claude calls `get_thesis` twice and contrasts.

### Check directional alignment

- *"Is NOW a bullish or bearish setup right now?"*
  → Claude calls `get_fit_score(ticker=NOW, opt_type=call)` and explains which signals are firing (sentiment, fundamentals, Kimi earnings grade, Kimi-vs-analyst delta, insider activity).
- *"Why does the screener say MSTR is high-fit for puts?"*
  → Claude calls `get_fit_score(ticker=MSTR, opt_type=put)` and walks through the bearish signals.

### Read the macro picture

- *"What's the current crash risk score and what's driving it?"*
  → Claude calls `get_crash_risk()` and explains the 6 components: yield curve, market breadth, VIX term structure, credit spreads, insider selling, earnings sentiment.
- *"How's geopolitical risk shaping up — is the Iran/China stuff getting worse?"*
  → Claude calls `get_geopolitical()` and summarizes the 5 region scores (Ukraine, Iran, China, Tariff, Fed-hawkishness).
- *"Is this a good regime to be opening Plan B trades?"*
  → Claude calls both `get_crash_risk()` and `get_geopolitical()` and gives you a synthesized read.

### Dig into a specific company's earnings

- *"What did Kimi say about NOW's most recent earnings?"*
  → Claude calls `get_earnings_analysis(ticker=NOW)` and pulls the verdict (BUY/HOLD/AVOID), bull case, bear case, EPS surprise %, analyst consensus.
- *"How did SNOW's last quarter compare to consensus?"*
  → Same tool — Claude walks through the divergence between Kimi's grade and analyst ratings.

### Compare option pricing across tickers (free, no Grok cost)

- *"Why are MRVL options so expensive but NVDA cheaper at similar prices?"*
  → Claude calls `get_iv(ticker=MRVL)` and `get_iv(ticker=NVDA)` and compares. Returns ATM IV, realized vol, RV percentile, IV/RV ratio, breakeven % move on the ATM call. Explains the IV gap with hard numbers, no LLM cost.
- *"Is the AVGO call I'm looking at expensive vs its 1-year history?"*
  → `get_iv(ticker=AVGO)` — returns where today's realized vol sits in 1y history (proxy for IV percentile), plus IV/RV ratio (>1.2 = market's pricing in MORE vol than recent realized; <0.9 = IV looks cheap).
- *"How rich is TSLA's 45-DTE IV right now?"*
  → `get_iv(ticker=TSLA, dte=45)` — ATM IV at the expiration nearest 45 days out, plus realized-vol context.

### Combine tools for richer questions

The real value: ask Claude to chain tools naturally.

- *"I'm thinking about buying a CRM call into earnings. Walk me through whether that's a good idea."*
  → Claude likely calls `get_fit_score` for direction, `get_earnings_analysis` for fundamentals context, then `get_thesis` for a specific contract you mention.
- *"Find me 3 high-conviction Plan B candidates for late May, then show me one specific contract for the top pick."*
  → Claude calls `scan_universe`, picks one, then calls `get_thesis` on it.
- *"Is now a good time to be aggressive on options, or should I sit on cash?"*
  → Claude calls `get_crash_risk` + `get_geopolitical` and synthesizes regime guidance.

### What this system does NOT do

Be aware of the boundaries — don't expect:

- ❌ Real-time stock prices (you can ask, but Claude pulls the price as a side-effect of `get_thesis`; standalone live-price queries aren't a tool)
- ❌ Historical price charts or technical indicators (no chart tool exposed)
- ❌ News headlines (the system reads SEC 8-K filings via Kimi, not news feeds — Grok pulls live X/Twitter sentiment but that surfaces inside `get_thesis`, not as a standalone tool)
- ❌ Multi-leg options strategies (iron condors, spreads, etc.) — only single-contract analysis
- ❌ Greeks for arbitrary strikes (only the strike you pass to `get_thesis` gets analyzed)
- ❌ Stock fundamentals by themselves (P/E, ROE, etc.) — those feed into `get_fit_score` but aren't directly queryable
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

- The thesis tool spends ~$0.0015 per call (Grok call to xAI). Don't
  loop it across 50 tickers.
- `scan_universe` is free + cached 5 min — call it freely.
- `get_crash_risk` and `get_earnings_analysis` are free + cached 6h.
- `get_iv` is free + cached 5 min.
- `get_geopolitical` is cached 5 min, refresh costs ~$0.0015.

Brady monitors usage per token at `/api/admin/usage`. If you're burning
calls in a way that surprises him, expect a friendly chat about
right-sized usage. Tokens are revocable.

## Privacy

Tool calls + arguments + token are logged on Brady's side for cost
attribution and debugging. He sees you exist, your token's alias, and
which tools you call (e.g. "alice ran scan_universe 5 times today").
He does NOT see your Claude conversation context — only the structured
tool inputs.

## Security audit

This MCP has been reviewed two ways. Both reports are reproducible.

### Automated audit (2026-05-10) — score 10/10

Run the static-analysis tool [mcp-audit](https://github.com/bradylandry/mcp-audit)
on this repo:

```bash
pip install git+https://github.com/bradylandry/mcp-audit.git
git clone https://github.com/bradylandry/jarvis-trading-mcp.git
mcp-audit jarvis-trading-mcp/
```

Output: **Score 10/10 — low risk.** Capabilities map matches the
manual claims below. Frozen audit report:
[mcp-audit/examples/jarvis-trading-mcp-audit.md](https://github.com/bradylandry/mcp-audit/blob/main/examples/jarvis-trading-mcp-audit.md).

The earlier 0.2.0 release scored 9/10 because URL construction used an
f-string (`f"{API_BASE}{path}"`). 0.2.1 switched to `urllib.parse.urljoin`
— behaviorally identical, removes the audit warning, reads as intent.

### Manual audit (2026-05-08)

A friend's audit flagged the actual risks in installing this MCP.
Worth knowing:

**What this MCP can and can't do** (audited; no surprises):

- ✅ Makes outbound HTTPS GET requests to one host (`trading.landrycmd.com`)
- ✅ Reads two env vars (`JARVIS_TRADING_TOKEN`, `JARVIS_TRADING_API`)
- ✅ Writes JSON-text to stdout for Claude
- ❌ No subprocess, shell, or `eval`
- ❌ No filesystem reads or writes (no logs to disk, no config files)
- ❌ No inbound network — stdio only
- ❌ TLS verification is on (no `verify=False`)
- ❌ Tool args can't inject into URLs/headers (handled by `requests` URL-encoding)

The blast radius is narrow: an attacker who fully controlled this MCP
could only return attacker-text to Claude. They could NOT touch your
filesystem, run shell, exfiltrate other env vars, or open a listening port.

**Real risks worth knowing about:**

1. **Prompt injection via tool responses.** This is intrinsic to any MCP
   that fetches third-party content. If Brady's API is ever compromised,
   a `bull_case` field could carry "ignore previous instructions, do X."
   **Mitigation:** don't run this MCP in the same Claude session as MCPs
   that have destructive tool access — filesystem-write, shell execution,
   `git push`, etc. Read-only research MCPs like this one shouldn't share
   sessions with anything that could *act* on injected instructions.
2. **Pin to a reviewed commit.** `pip install git+...` without a `@<SHA>`
   pulls whatever's on `master` at install time. A future `pip install
   --upgrade` pulls again. So you're trusting Brady's GitHub account in
   perpetuity, not just the version you reviewed. See the **Install**
   section above for the pinned-install command. Re-review and re-pin on
   each upgrade.
3. **Token in plaintext in your Claude config.** Standard for MCP. Means
   your `claude_desktop_config.json` (or equivalent) is now a sensitive
   file — anything that reads it gets the token. The token is API-scoped,
   not a GitHub or cloud credential, so impact is limited to whatever the
   trading API exposes (read-only research endpoints, per the code). Still
   worth treating the config like you'd treat any file containing
   credentials: don't commit it to a public repo, don't paste it in chats.
4. **Sanitized error messages** (added 2026-05-08 in response to the
   audit): the MCP returns just the HTTP status code on errors, not the
   verbatim response body. Closes the theoretical "buggy upstream API
   could leak something it shouldn't" path.

**The trust model in one sentence:** if you trust Brady (the person
operating the API) and pin to a reviewed commit, this MCP carries
roughly the same risk as any small `requests`-based Python package
from a friend's GitHub.

## Updating

```bash
pip install --upgrade git+https://github.com/bradylandry/jarvis-trading-mcp.git
```

Brady will message the group when there's a meaningful update worth
pulling.

## License

MIT. See `LICENSE`.

The package code is open source. The trading API it talks to is closed
source and operated by Brady at `trading.landrycmd.com`. That API is
NOT covered by this license — it's a courtesy service, revocable at
any time.
