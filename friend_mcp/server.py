"""friend_mcp.server — remote, OAuth-gated MCP server for the Jarvis Trading research API.

Tier 1 rewrite: ports the original local stdio bridge to a remote, authenticated HTTP
server mirroring the vault-mcp-server pattern. Same 7 read-only tools, same trading API
(trading.landrycmd.com), same client-side rate limiter, now reachable by Claude web /
desktop / mobile behind Entra OAuth.

Auth model:
  - Client -> this server: Entra OAuth (AzureProvider), the *landrycmd* tenant. Enabled only
    when AUTH_CLIENT_ID is set (i.e. in the deployed Container App); omitted locally so
    loopback dev runs without a token. Fails CLOSED on a public bind (see main()).
  - This server -> trading API: static X-API-Token, sourced from macOS Keychain (local, via
    JARVIS_TRADING_TOKEN set by run-local.sh) or Azure Key Vault via Managed Identity (in
    Azure). Never written to disk.

All tools are read-only research: none place orders, move funds, or write anything.

Env vars:
  # user auth (deployed only; landrycmd tenant)
  AUTH_CLIENT_ID, AUTH_CLIENT_SECRET, AUTH_TENANT_ID, PUBLIC_BASE_URL
  # backend token (one source required):
  JARVIS_TRADING_TOKEN                        -> local dev (from Keychain via run-local.sh)
  KEY_VAULT_URL + JARVIS_TOKEN_SECRET_NAME    -> Azure (pull via Managed Identity)
  # backend + limits
  JARVIS_TRADING_API                -> base URL (default https://trading.landrycmd.com)
  JARVIS_TRADING_MAX_CALLS_PER_MIN  -> client-side rate cap (default 30)
  # transport
  HOST (default 0.0.0.0), PORT (default 8080), ALLOW_UNAUTHENTICATED

Research and informational only. Not financial advice.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from urllib.parse import urljoin

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth.providers.azure import AzureProvider

API_BASE = os.environ.get("JARVIS_TRADING_API", "https://trading.landrycmd.com").rstrip("/")
TIMEOUT_S = 90
RATE_LIMIT_MAX_CALLS = int(os.environ.get("JARVIS_TRADING_MAX_CALLS_PER_MIN", "30"))
RATE_LIMIT_WINDOW_S = 60

# --- User authentication (Entra OAuth). Enabled only when AUTH_CLIENT_ID is set (deployed). ---
_auth = None
if os.environ.get("AUTH_CLIENT_ID"):
    _auth = AzureProvider(
        client_id=os.environ["AUTH_CLIENT_ID"],
        client_secret=os.environ.get("AUTH_CLIENT_SECRET"),
        tenant_id=os.environ["AUTH_TENANT_ID"],
        required_scopes=["read"],
        base_url=os.environ["PUBLIC_BASE_URL"],
    )

mcp = FastMCP(
    "Jarvis Trading",
    instructions=(
        "Read-only options and market-research tools backed by the Jarvis Trading API. "
        "Every tool is analysis only: none place orders, move funds, or write anything. "
        "Cite figures as coming from Jarvis Trading. Research and informational only, not "
        "financial advice."
    ),
    auth=_auth,
)


# --- Backend token: Keychain/env locally, Key Vault via Managed Identity in Azure. Lazy + cached. ---
_token_cache: str | None = None
_token_lock = threading.Lock()


def _backend_token() -> str:
    global _token_cache
    if _token_cache:
        return _token_cache
    with _token_lock:
        if _token_cache:
            return _token_cache
        tok = os.environ.get("JARVIS_TRADING_TOKEN")
        if not tok:
            kv = os.environ.get("KEY_VAULT_URL")
            name = os.environ.get("JARVIS_TOKEN_SECRET_NAME")
            if kv and name:
                # Imported lazily so local dev needs no azure packages installed.
                from azure.identity import ManagedIdentityCredential
                from azure.keyvault.secrets import SecretClient
                tok = SecretClient(
                    vault_url=kv, credential=ManagedIdentityCredential()
                ).get_secret(name).value
        if not tok:
            raise RuntimeError(
                "backend token unavailable: set JARVIS_TRADING_TOKEN (local) or "
                "KEY_VAULT_URL + JARVIS_TOKEN_SECRET_NAME (Azure)"
            )
        _token_cache = tok
        return _token_cache


# --- Client-side rate limiter (sliding window). Locked: the HTTP transport can serve concurrently
#     (unlike the old stdio loop), so the deque needs a lock. Protects the upstream API budget from
#     runaway tool-call loops. ---
_call_history: deque[float] = deque()
_rate_lock = threading.Lock()


def _rate_limit_check() -> None:
    now = time.monotonic()
    with _rate_lock:
        cutoff = now - RATE_LIMIT_WINDOW_S
        while _call_history and _call_history[0] < cutoff:
            _call_history.popleft()
        if len(_call_history) >= RATE_LIMIT_MAX_CALLS:
            wait_s = max(0, int(_call_history[0] + RATE_LIMIT_WINDOW_S - now))
            raise RuntimeError(
                f"client-side rate limit hit ({RATE_LIMIT_MAX_CALLS}/{RATE_LIMIT_WINDOW_S}s); "
                f"wait ~{wait_s}s. Protects the upstream API budget from runaway loops. "
                f"Raise JARVIS_TRADING_MAX_CALLS_PER_MIN if genuinely needed."
            )
        _call_history.append(now)


def _api_get(path: str, params: dict | None = None) -> dict | list:
    """GET the trading API with the X-API-Token header. Read-only; each tool's `path` is
    hard-coded (never user-controlled). Upstream error bodies are not passed into the model
    context (info-leak hygiene)."""
    _rate_limit_check()
    resp = httpx.get(
        urljoin(API_BASE + "/", path.lstrip("/")),
        params=params or {},
        headers={"X-API-Token": _backend_token(), "Accept": "application/json"},
        timeout=TIMEOUT_S,
    )
    if resp.status_code == 401:
        raise RuntimeError("trading API rejected the token (401). Confirm the token is still active.")
    if resp.status_code != 200:
        raise RuntimeError(f"trading API returned status {resp.status_code}.")
    return resp.json()


@mcp.tool
def scan_universe(mode: str = "plan_b", budget: float = 75.0, opt_type: str = "call") -> dict | list:
    """Scan the curated ~50-name liquid optionable universe; returns top candidates ranked by
    fit_score under the chosen hunt mode. mode: plan_b | plan_a | directional. budget: max
    premium per contract in $. opt_type: call | put."""
    return _api_get("/api/options/scan/universe", {"mode": mode, "budget": budget, "type": opt_type})


@mcp.tool
def get_thesis(ticker: str, strike: float, expiration: str, opt_type: str = "call") -> dict:
    """Grok + Kimi thesis for a specific options contract: verdict, bull/bear case, exit plan,
    gated on catalyst window, IV regime, market regime, and directional fit.
    expiration: YYYY-MM-DD. opt_type: call | put."""
    return _api_get("/api/options/thesis", {
        "ticker": ticker.upper(), "strike": strike, "expiration": expiration, "type": opt_type,
    })


@mcp.tool
def get_fit_score(ticker: str, opt_type: str = "call") -> dict:
    """Directional fit score (0-10) for a ticker with per-component evidence: sentiment,
    fundamentals, Kimi earnings, Kimi-vs-analyst delta, insider activity."""
    return _api_get("/api/screener", {"tickers": ticker.upper()})


@mcp.tool
def get_crash_risk() -> dict:
    """Composite market crash-risk score (0-10) with 6 leading-indicator components: yield
    curve, breadth, VIX term structure, credit spreads, insider selling, earnings sentiment."""
    return _api_get("/api/macro/crash-risk")


@mcp.tool
def get_earnings_analysis(ticker: str) -> dict:
    """Most recent Kimi-graded SEC 8-K deep-dive: BUY/HOLD/AVOID verdict + thesis, conviction,
    deep-dive narrative, numbers breakdown, bull/bear case, forward catalysts/risks, 12-month
    outlook, analyst-consensus disagreement. Empty if the ticker hasn't been analyzed."""
    return _api_get("/api/macro/earnings-analyses", {"ticker": ticker.upper()})


@mcp.tool
def get_geopolitical() -> dict:
    """Multi-region geopolitical risk + macro regime signal: Ukraine, Iran, China-Taiwan,
    tariff risk, Fed hawkishness, each scored 0-10."""
    return _api_get("/api/macro/political")


@mcp.tool
def get_iv(ticker: str, dte: int = 30) -> dict:
    """ATM implied vol + realized-vol context for one ticker at the expiration nearest `dte`
    days out. Returns spot, ATM call/put bid/ask/mid/IV/volume/OI/spread, 30d realized vol,
    RV percentile (1y), IV/RV ratio, breakeven % move on the ATM call, and a summary line.
    Cheap (no LLM cost, cached 5min) — use for 'is this option expensive' questions."""
    return _api_get("/api/options/iv", {"ticker": ticker.upper(), "dte": int(dte)})


def main() -> None:
    """Start the remote (streamable-http) MCP server. Console-script + `python -m` entrypoint."""
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    # Fail CLOSED: never expose a non-loopback HTTP transport without authentication.
    if _auth is None and host not in ("127.0.0.1", "localhost") \
            and os.environ.get("ALLOW_UNAUTHENTICATED") != "1":
        raise SystemExit(
            "refusing to start remote HTTP transport without authentication; "
            "set AUTH_CLIENT_ID, bind HOST=127.0.0.1, or set ALLOW_UNAUTHENTICATED=1 to override"
        )
    mcp.run(transport="http", host=host, port=port)


if __name__ == "__main__":
    main()
