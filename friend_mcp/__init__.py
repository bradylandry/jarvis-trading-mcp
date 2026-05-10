"""friend_mcp — Claude MCP server exposing Brady's jarvis-trading research tools.

For 2-3 trusted friends to access fit_score, options thesis, crash risk,
and earnings analysis from inside their own Claude sessions. Each friend
gets a unique X-API-Token; usage is logged + cost-attributed on the server.

Stdio transport: friends install this package locally, add it to their
Claude config, set their token as an env var. Their Claude session calls
tools on this server, which makes HTTP calls to the public trading API
with the friend's token, and returns results to Claude.

Research-only / informational. No SLA. Not financial advice.
"""

__version__ = "0.1.0"
