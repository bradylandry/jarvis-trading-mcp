"""friend_mcp.server — MCP server bridging Claude → jarvis-trading research API.

A small stdio MCP server that friends install locally + register in their
Claude Desktop / Claude Code config. Each tool call hits the public
trading-site API at https://trading.landrycmd.com with the friend's
X-API-Token (set via env var JARVIS_TRADING_TOKEN). The server itself
holds no credentials beyond what the friend sets — Brady controls token
issuance and revocation centrally on the server side.

Tools exposed:

  - scan_universe(mode, budget, opt_type)
      Curated 50-name liquid optionable universe scan. Returns top
      candidates ranked by fit_score under the chosen hunt mode.

  - get_thesis(ticker, strike, expiration, opt_type)
      Plain-English thesis from Grok + Kimi A/B for a specific contract.
      Includes catalyst + IV + market-regime + directional-fit gating.

  - get_fit_score(ticker, opt_type)
      Directional alignment score (0-10) with sentiment / fundamentals /
      Kimi-earnings / Kimi-vs-analyst-disagreement / insider components.

  - get_crash_risk()
      Composite market regime score (0-10) with 6 component breakdown.

  - get_earnings_analysis(ticker)
      Most recent Kimi-graded SEC 8-K analysis: verdict, bull/bear case,
      analyst consensus, EPS surprise.

  - get_geopolitical()
      Multi-region geopolitical risk signal: Ukraine, Iran, China,
      Tariff, Fed-hawkishness scores 0-10.

Cost: each tool call counted on the server; friends incur no direct $
cost (Brady absorbs API spend, monitors via /api/admin/usage).

Disclaimer: research and informational only. Not financial advice.
Brady provides this as a courtesy to friends; no SLA, no guarantees on
data freshness or correctness, no liability for trading decisions made
based on outputs.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import requests

# Read at startup; surfaced on first tool call if missing.
API_BASE  = os.environ.get("JARVIS_TRADING_API", "https://trading.landrycmd.com").rstrip("/")
API_TOKEN = os.environ.get("JARVIS_TRADING_TOKEN", "")
TIMEOUT_S = 90


# ── Generic API helpers ────────────────────────────────────────────────────

def _api_get(path: str, params: dict | None = None) -> dict:
    """GET request to the trading API. Surfaces auth errors as a structured
    response Claude can show the user instead of crashing the MCP server."""
    if not API_TOKEN:
        return {
            "error": (
                "JARVIS_TRADING_TOKEN env var is not set. Ask Brady for "
                "your access token, then add it to your Claude config "
                "under env: { JARVIS_TRADING_TOKEN: \"tok_...\" }."
            ),
        }
    try:
        resp = requests.get(
            f"{API_BASE}{path}",
            params=params or {},
            headers={"X-API-Token": API_TOKEN, "Accept": "application/json"},
            timeout=TIMEOUT_S,
        )
        if resp.status_code == 401:
            return {"error": "Token rejected. Confirm with Brady that your token is still active."}
        if resp.status_code != 200:
            # Don't pass response body verbatim into Claude's context.
            # Upstream-error text could in theory carry leaked content
            # (a buggy server, a misconfigured proxy, an attacker-controlled
            # response on a compromised host). Status code alone is enough
            # for Claude to surface "the API returned an error" to the user;
            # if more detail is needed, the user can ping Brady out-of-band.
            # Friend security audit 2026-05-08 flagged this verbatim
            # passthrough as low-but-real info-leak risk; sanitized here.
            return {"error": f"API returned status {resp.status_code}. If this persists, contact Brady."}
        return resp.json()
    except requests.Timeout:
        return {"error": f"Timeout calling {path} (waited {TIMEOUT_S}s)"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ── Tool implementations ───────────────────────────────────────────────────

def scan_universe(mode: str = "plan_b", budget: float = 75.0, opt_type: str = "call") -> dict:
    """Scan curated optionable universe. Returns top candidates per hunt mode."""
    return _api_get("/api/options/scan/universe", {
        "mode": mode,
        "budget": budget,
        "type": opt_type,
    })


def get_thesis(ticker: str, strike: float, expiration: str, opt_type: str = "call") -> dict:
    """Grok + Kimi A/B thesis for a specific contract. Includes verdict +
    bull/bear case + exit plan, gated on catalyst window, IV regime, market
    regime, and directional fit."""
    return _api_get("/api/options/thesis", {
        "ticker":     ticker.upper(),
        "strike":     strike,
        "expiration": expiration,
        "type":       opt_type,
    })


def get_fit_score(ticker: str, opt_type: str = "call") -> dict:
    """Directional fit score (0-10) for ticker + option direction. Returns
    score + per-component evidence (sentiment, fundamentals, Kimi earnings,
    Kimi-vs-analyst delta, insider activity)."""
    # No direct endpoint — the universe scan returns it per candidate. To
    # get a single ticker, use the thesis endpoint and pull contract.fit_score
    # from the response. But the cleanest single-ticker call we have is
    # the screener's directional_fit via the screener endpoint.
    return _api_get("/api/screener", {"tickers": ticker.upper()})


def get_crash_risk() -> dict:
    """Composite market crash-risk score (0-10) with 6 leading-indicator
    components. Yield curve, breadth, VIX term, credit spreads, insider
    selling acceleration, earnings sentiment."""
    return _api_get("/api/macro/crash-risk")


def get_earnings_analysis(ticker: str) -> dict:
    """Most recent Kimi-graded SEC 8-K analysis for the ticker. Returns a
    deep-dive analyst take embedded in the kimi_analysis JSON: BUY/HOLD/AVOID
    verdict + 3-5 sentence verdict_thesis explaining why; conviction
    HIGH/MEDIUM/LOW; 3-5 paragraph deep_dive narrative; numbers_breakdown
    (EPS/rev surprise %, margin movement, cash flow); bull/bear case;
    forward key_catalysts and key_risks arrays; twelve_month_outlook
    qualitative narrative; analyst-consensus disagreement signal.
    Empty if Brady's system hasn't analyzed this ticker."""
    return _api_get("/api/macro/earnings-analyses", {"ticker": ticker.upper()})


def get_geopolitical() -> dict:
    """Multi-region geopolitical risk + macro regime signals."""
    return _api_get("/api/macro/political")


def get_iv(ticker: str, dte: int = 30) -> dict:
    """ATM implied vol + realized-vol context for one ticker at the
    expiration nearest `dte` days out. Free (no LLM cost — pulls from
    yfinance), cached 5min server-side. Returns spot, expiration, ATM
    call/put bid/ask/mid/IV/volume/OI/spread, 30d realized vol, RV
    percentile in 1y history, IV/RV ratio, breakeven % move on the ATM
    call, and a plain-English summary line. Use this to answer 'is this
    option expensive' or 'compare option pricing across two tickers'
    without spending $0.0015/call on get_thesis()."""
    return _api_get("/api/options/iv", {"ticker": ticker.upper(), "dte": int(dte)})


# ── MCP protocol implementation (stdio JSON-RPC 2.0) ──────────────────────
#
# We implement the bare minimum of MCP needed for Claude Desktop / Claude
# Code to discover + invoke tools. Avoids the heavier `mcp` SDK so this
# package has only one runtime dep (requests).

TOOLS = [
    {
        "name": "scan_universe",
        "description": "Scan a curated 50-name liquid optionable universe. Returns top contracts ranked by fit_score, filtered by hunt mode. Use when looking for candidate options trades.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode":     {"type": "string", "enum": ["plan_b", "plan_a", "directional"], "default": "plan_b"},
                "budget":   {"type": "number", "default": 75, "description": "Max premium per contract in $"},
                "opt_type": {"type": "string", "enum": ["call", "put"], "default": "call"},
            },
        },
    },
    {
        "name": "get_thesis",
        "description": "Grok + Kimi A/B thesis for a specific options contract. Includes verdict, bull/bear case, exit plan. Use when evaluating a single contract you're considering trading.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker":     {"type": "string"},
                "strike":     {"type": "number"},
                "expiration": {"type": "string", "description": "YYYY-MM-DD"},
                "opt_type":   {"type": "string", "enum": ["call", "put"], "default": "call"},
            },
            "required": ["ticker", "strike", "expiration"],
        },
    },
    {
        "name": "get_fit_score",
        "description": "Directional fit score (0-10) for ticker + direction. Components: sentiment, fundamentals, Kimi earnings, Kimi-vs-analyst disagreement, insider activity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker":   {"type": "string"},
                "opt_type": {"type": "string", "enum": ["call", "put"], "default": "call"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_crash_risk",
        "description": "Composite market crash-risk score (0-10) with 6 leading-indicator components: yield curve, market breadth, VIX term structure, credit spreads, insider selling, earnings sentiment.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_earnings_analysis",
        "description": "Most recent Kimi-graded SEC 8-K deep-dive analysis: BUY/HOLD/AVOID verdict + 3-5 sentence verdict_thesis explaining why, conviction (HIGH/MEDIUM/LOW), 3-5 paragraph deep_dive narrative, numbers_breakdown, bull/bear case, forward key_catalysts + key_risks, 12-month qualitative outlook, analyst consensus disagreement signal.",
        "inputSchema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_geopolitical",
        "description": "Multi-region geopolitical risk signal: Ukraine, Iran, China-Taiwan, Tariff risk, Fed hawkishness — each scored 0-10.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_iv",
        "description": "ATM implied vol + realized-vol context for one ticker. Returns spot, ATM call+put bid/ask/mid/IV/volume/OI/spread at the expiration nearest `dte` days, plus 30d realized vol, RV percentile in 1y history, IV/RV ratio, breakeven % move on the ATM call, and a plain-English summary. Use this for 'is this option expensive' or 'compare option pricing across tickers' questions — free (no LLM cost), cached 5min. Cheaper than get_thesis() when you don't need a full Grok narrative.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock symbol e.g. 'NVDA'"},
                "dte":    {"type": "integer", "default": 30, "description": "Target days-to-expiry; nearest listed expiration is picked."},
            },
            "required": ["ticker"],
        },
    },
]


TOOL_FNS = {
    "scan_universe":         scan_universe,
    "get_thesis":            get_thesis,
    "get_fit_score":         get_fit_score,
    "get_crash_risk":        get_crash_risk,
    "get_earnings_analysis": get_earnings_analysis,
    "get_geopolitical":      get_geopolitical,
    "get_iv":                get_iv,
}


def _send(msg: dict) -> None:
    """Write a single JSON-RPC message to stdout."""
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _handle(msg: dict) -> dict | None:
    """Process one JSON-RPC request and return the response (or None for
    notifications). Implements the subset of MCP needed for tool listing
    + invocation."""
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "friend_mcp", "version": "0.1.0"},
            },
        }

    if method == "notifications/initialized":
        return None  # notification, no response expected

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = TOOL_FNS.get(name)
        if not fn:
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"},
            }
        try:
            result = fn(**args)
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
            }
        except TypeError as e:
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32602, "message": f"Invalid params for {name}: {e}"},
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32603, "message": f"Tool {name} failed: {e}"},
            }

    # Unknown method — return method-not-found
    if msg_id is not None:
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return None


def main() -> None:
    """Stdio loop: read JSON-RPC messages line-by-line from stdin, dispatch,
    write responses to stdout. This is what Claude Desktop / Claude Code
    drive when the MCP server is added to their config."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = _handle(msg)
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
