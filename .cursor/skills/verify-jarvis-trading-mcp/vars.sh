# Shared settings for every block in SKILL.md and features/. Source it from the repo root:
#   . .cursor/skills/verify-jarvis-trading-mcp/vars.sh
# Override any of these in the environment first to run a second pair side by side.
: "${EVIDENCE:=/tmp/verify-jarvis-trading-mcp}"
: "${PAPER_PORT:=8765}"   # paper research API
: "${MCP_PORT:=8080}"     # main server, token from JARVIS_TRADING_TOKEN=paper
: "${ROT_PORT:=8081}"     # rotation server, token from the fake Key Vault
: "${SIGNIN_PORT:=8082}"  # short-lived servers started by signin_matrix.py
: "${SCRATCH:=/tmp/verify-jarvis-trading-mcp-scratch-${PAPER_PORT}}"
SKILL_DIR=.cursor/skills/verify-jarvis-trading-mcp
API_URL="http://127.0.0.1:${PAPER_PORT}"
# Placeholder backend tokens for the rotation journeys. Not secrets. Only the last 4
# characters (OLD1, NEW2, NEW3, BAD4) may appear in evidence; leakcheck enforces that.
ROT_OLD=placeholder-rotation-token-OLD1
ROT_NEW=placeholder-rotation-token-NEW2
ROT_NEXT=placeholder-rotation-token-NEW3
ROT_BAD=placeholder-rotation-token-BAD4
export EVIDENCE PAPER_PORT MCP_PORT ROT_PORT SIGNIN_PORT SCRATCH

# Atomically replace a token file, so a reader never sees a half-written value.
set_token() { printf '%s\n' "$2" > "$1.tmp" && mv "$1.tmp" "$1"; }

case "$API_URL" in
  http://127.0.0.1:[0-9]*) ;;
  *) echo "refusing non-loopback JARVIS_TRADING_API" >&2; return 1 2>/dev/null || exit 1 ;;
esac
