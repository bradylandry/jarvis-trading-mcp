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
# Placeholder sign-in secret. Must equal SECRET in signin_matrix.py; the final leakcheck scans for it.
SIGNIN_SECRET=placeholder-client-secret-x9Q4
export EVIDENCE PAPER_PORT MCP_PORT ROT_PORT SIGNIN_PORT SCRATCH

# Atomically replace a token file, so a reader never sees a half-written value.
set_token() { (umask 077; printf '%s\n' "$2" > "$1.tmp") && mv "$1.tmp" "$1"; }

# Every process this skill starts gets both cases of each proxy variable pointed at a closed
# loopback port, and loopback in no_proxy, so a stray non-loopback request fails instead of
# leaving the machine. Python prefers the lowercase names, so both cases are always set.
NOPROXY_ENV=(
  HTTP_PROXY=http://127.0.0.1:9 http_proxy=http://127.0.0.1:9
  HTTPS_PROXY=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9
  ALL_PROXY=http://127.0.0.1:9 all_proxy=http://127.0.0.1:9
  NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
)
# Unset inherited Azure credential settings and point managed identity at a closed loopback
# port, so a real Azure SDK that slipped past the fake_kv shadow cannot get a token.
NOCLOUD_ENV=()
for _v in $(compgen -e); do
  case "$_v" in AZURE_*|IDENTITY_*|MSI_*) NOCLOUD_ENV+=(-u "$_v") ;; esac
done
unset _v
NOCLOUD_ENV+=(MSI_ENDPOINT=http://127.0.0.1:9 IDENTITY_ENDPOINT=http://127.0.0.1:9)

# Print the pid in $EVIDENCE/<name>.pid only if that process is alive and is the one this
# skill started (its command line names the right program and port). A stale pid file can
# point at a recycled pid that belongs to someone else; never signal it.
our_pid() {
  local file="$EVIDENCE/$1.pid" pid args port
  [ -s "$file" ] || return 1
  pid=$(cat "$file")
  case "$pid" in ''|*[!0-9]*) return 1 ;; esac
  args=$(ps -ww -p "$pid" -o args= 2>/dev/null) || return 1
  case "$1" in
    paper)
      case "$args" in *paper_backend.py*"--port $PAPER_PORT"*) ;; *) return 1 ;; esac ;;
    mcp|rot|signin)
      case "$args" in *friend_mcp.server*) ;; *) return 1 ;; esac
      case "$1" in mcp) port=$MCP_PORT ;; rot) port=$ROT_PORT ;; *) port=$SIGNIN_PORT ;; esac
      if [ -r "/proc/$pid/environ" ]; then
        tr '\0' '\n' < "/proc/$pid/environ" | grep -qx "PORT=$port" || return 1
      fi ;;
    *) return 1 ;;
  esac
  printf '%s\n' "$pid"
}

case "$SCRATCH" in
  *..*) echo "refusing SCRATCH containing ..: $SCRATCH" >&2; return 1 2>/dev/null || exit 1 ;;
esac

case "$API_URL" in
  http://127.0.0.1:[0-9]|http://127.0.0.1:[0-9][0-9]|http://127.0.0.1:[0-9][0-9][0-9]|http://127.0.0.1:[0-9][0-9][0-9][0-9]|http://127.0.0.1:[0-9][0-9][0-9][0-9][0-9]) ;;
  *) echo "refusing non-loopback JARVIS_TRADING_API" >&2; return 1 2>/dev/null || exit 1 ;;
esac
