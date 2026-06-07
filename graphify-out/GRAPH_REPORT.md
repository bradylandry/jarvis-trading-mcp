# Graph Report - .  (2026-06-06)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 57 nodes · 64 edges · 13 communities (6 shown, 7 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `f84d5046`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]

## God Nodes (most connected - your core abstractions)
1. `jarvis-trading-mcp` - 17 edges
2. `_api_get()` - 10 edges
3. `What you can ask Claude` - 10 edges
4. `main()` - 4 edges
5. `_rate_limit_check()` - 3 edges
6. `scan_universe()` - 3 edges
7. `get_thesis()` - 3 edges
8. `get_fit_score()` - 3 edges
9. `get_crash_risk()` - 3 edges
10. `get_earnings_analysis()` - 3 edges

## Surprising Connections (you probably didn't know these)
- `get_crash_risk()` --calls--> `_api_get()`  [EXTRACTED]
  friend_mcp/server.py → friend_mcp/server.py  _Bridges community 4 → community 7_
- `get_earnings_analysis()` --calls--> `_api_get()`  [EXTRACTED]
  friend_mcp/server.py → friend_mcp/server.py  _Bridges community 4 → community 8_
- `get_fit_score()` --calls--> `_api_get()`  [EXTRACTED]
  friend_mcp/server.py → friend_mcp/server.py  _Bridges community 4 → community 3_
- `get_geopolitical()` --calls--> `_api_get()`  [EXTRACTED]
  friend_mcp/server.py → friend_mcp/server.py  _Bridges community 4 → community 9_
- `get_iv()` --calls--> `_api_get()`  [EXTRACTED]
  friend_mcp/server.py → friend_mcp/server.py  _Bridges community 4 → community 10_

## Import Cycles
- None detected.

## Communities (13 total, 7 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.12
Nodes (15): Configure Claude Code, Configure Claude Desktop, Cost / quota, Disclaimer, Install, jarvis-trading-mcp, License, Privacy (+7 more)

### Community 1 - "Community 1"
Cohesion: 0.20
Nodes (10): Check directional alignment, Combine tools for richer questions, Compare option pricing across tickers (free, no Grok cost), Dig into a specific company's earnings, Evaluate a specific contract, Find a trade, Quick reference card, Read the macro picture (+2 more)

### Community 2 - "Community 2"
Cohesion: 0.33
Nodes (6): _handle(), main(), Write a single JSON-RPC message to stdout., Process one JSON-RPC request and return the response (or None for     notificati, Stdio loop: read JSON-RPC messages line-by-line from stdin, dispatch,     write, _send()

### Community 3 - "Community 3"
Cohesion: 0.50
Nodes (3): get_fit_score(), friend_mcp.server — MCP server bridging Claude → jarvis-trading research API.  A, Directional fit score (0-10) for ticker + option direction. Returns     score +

### Community 4 - "Community 4"
Cohesion: 0.50
Nodes (4): _api_get(), _rate_limit_check(), GET request to the trading API. Surfaces auth errors as a structured     respons, Sliding-window rate check. Returns an error dict if the limit is hit;     None i

### Community 5 - "Community 5"
Cohesion: 0.67
Nodes (3): Automated audit (2026-05-10) — score 10/10, Manual audit (2026-05-08), Security audit

## Knowledge Gaps
- **25 isolated node(s):** `What this actually is`, `Trust model in one sentence`, `Tools added to your Claude session`, `Disclaimer`, `Source code overview (audit-ready)` (+20 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `jarvis-trading-mcp` connect `Community 0` to `Community 1`, `Community 5`?**
  _High betweenness centrality (0.214) - this node is a cross-community bridge._
- **Why does `What you can ask Claude` connect `Community 1` to `Community 0`?**
  _High betweenness centrality (0.134) - this node is a cross-community bridge._
- **Why does `_api_get()` connect `Community 4` to `Community 3`, `Community 7`, `Community 8`, `Community 9`, `Community 10`, `Community 11`, `Community 12`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **What connects `friend_mcp — Claude MCP server exposing Brady's jarvis-trading research tools.`, `friend_mcp.server — MCP server bridging Claude → jarvis-trading research API.  A`, `Sliding-window rate check. Returns an error dict if the limit is hit;     None i` to the rest of the system?**
  _39 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.125 - nodes in this community are weakly interconnected._