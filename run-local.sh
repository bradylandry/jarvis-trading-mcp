#!/usr/bin/env bash
# Local dev: pull the trading X-API-Token from the macOS Keychain (never on disk),
# bind to loopback (so the fail-closed guard is satisfied without OAuth), and run the
# streamable-http server. Store the token once with:
#   security add-generic-password -a "$USER" -s jarvis-trading -w '<X-API-Token>'
set -euo pipefail
export JARVIS_TRADING_TOKEN="$(security find-generic-password -a "$USER" -s jarvis-trading -w)"
export JARVIS_TRADING_API="${JARVIS_TRADING_API:-https://trading.landrycmd.com}"
export HOST=127.0.0.1 PORT="${PORT:-8080}"
exec python -m friend_mcp.server
