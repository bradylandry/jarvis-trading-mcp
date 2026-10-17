#!/usr/bin/env python3
"""MCP client checks for the verify skill.

doctor: list tools. Does not call the research API.
drive: call one tool and confirm the paper backend saw a single GET.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from fastmcp import Client

EXPECTED_TOOLS = {
    "scan_universe",
    "get_thesis",
    "get_fit_score",
    "get_crash_risk",
    "get_earnings_analysis",
    "get_geopolitical",
    "get_iv",
}

# Upstream path each tool hits in friend_mcp/server.py. opt_type is sent as "type".
UPSTREAM_PATH = {
    "scan_universe": "/api/options/scan/universe",
    "get_thesis": "/api/options/thesis",
    "get_fit_score": "/api/screener",
    "get_crash_risk": "/api/macro/crash-risk",
    "get_earnings_analysis": "/api/macro/earnings-analyses",
    "get_geopolitical": "/api/macro/political",
    "get_iv": "/api/options/iv",
}

ORDER_MARKERS = ("order", "buy", "sell")


def _require_loopback(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost"):
        raise SystemExit(f"refusing non-loopback MCP URL: {parsed.scheme}://{parsed.hostname}")
    if not parsed.path.rstrip("/").endswith("/mcp"):
        raise SystemExit("MCP URL must end in /mcp")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _content_text(result) -> list[str]:
    texts = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text is not None:
            texts.append(text)
    return texts


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    return str(value)


async def _list_tools(url: str) -> list[dict]:
    async with Client(url, timeout=20) as client:
        tools = await client.list_tools()
    return [{"name": tool.name, "description": tool.description or ""} for tool in tools]


async def _call_tool(url: str, name: str, arguments: dict):
    async with Client(url, timeout=30) as client:
        return await client.call_tool(name, arguments)


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _paper_body(result) -> dict | None:
    """Return the fixture object, including when FastMCP wraps a list as result."""
    candidates = [result.data]
    structured = result.structured_content
    if isinstance(structured, dict):
        candidates.append(structured)
        if isinstance(structured.get("result"), list):
            candidates.extend(structured["result"])
    if isinstance(result.data, list):
        candidates.extend(result.data)
    for item in candidates:
        if isinstance(item, dict) and "paper" in item:
            return item
    return None


def doctor(url: str, evidence: Path, access_log: Path) -> None:
    if not access_log.exists():
        raise SystemExit(f"missing paper access log: {access_log}")
    before = _read_jsonl(access_log)
    tools = asyncio.run(_list_tools(url))
    after = _read_jsonl(access_log)
    names = [tool["name"] for tool in tools]
    payload = {"count": len(tools), "tools": tools, "upstream_requests_added": len(after) - len(before)}
    _write(evidence / "tools.json", payload)
    missing = EXPECTED_TOOLS - set(names)
    extra = set(names) - EXPECTED_TOOLS
    forbidden = [name for name in names if any(marker in name.lower() for marker in ORDER_MARKERS)]
    if missing or extra or forbidden or len(after) != len(before):
        print(json.dumps({
            "ok": False,
            "missing": sorted(missing),
            "extra": sorted(extra),
            "forbidden": forbidden,
            "upstream_requests_added": len(after) - len(before),
        }, indent=2))
        raise SystemExit(1)
    print("doctor ok")
    for name in names:
        print(name)
    print("upstream_requests_added 0")


def drive(url: str, evidence: Path, access_log: Path, tool: str, arguments: dict) -> None:
    if tool not in UPSTREAM_PATH:
        raise SystemExit(f"unknown tool {tool}")
    if not access_log.exists():
        raise SystemExit(f"missing paper access log: {access_log}")
    before = _read_jsonl(access_log)
    result = asyncio.run(_call_tool(url, tool, arguments))
    after = _read_jsonl(access_log)
    new_rows = after[len(before):]
    call_payload = {
        "tool": tool,
        "arguments": arguments,
        "is_error": result.is_error,
        "structured_content": _jsonable(result.structured_content),
        "data": _jsonable(result.data),
        "text": _content_text(result),
    }
    _write(evidence / f"call-{tool}.json", call_payload)
    body = _paper_body(result)
    paper = body is not None and body.get("paper") is True
    orders = body.get("orders_placed") if body else None
    expected_path = UPSTREAM_PATH[tool]
    paths_ok = bool(new_rows) and all(row.get("path") == expected_path for row in new_rows)
    methods_ok = bool(new_rows) and all(row.get("method") == "GET" for row in new_rows)
    status_ok = all(row.get("status") == 200 for row in new_rows)
    token_ok = all(row.get("token_present") is True and row.get("token_last4") == "aper" for row in new_rows)
    side = {
        "tool": tool,
        "upstream_path": expected_path,
        "new_requests": new_rows,
        "all_get": methods_ok,
        "path_matched": paths_ok,
        "status_200": status_ok,
        "paper_token_last4": token_ok,
        "paper": paper,
        "orders_placed": orders,
    }
    _write(evidence / "side-effects.json", side)
    ok = (
        not result.is_error
        and methods_ok
        and paths_ok
        and status_ok
        and token_ok
        and paper
        and orders == 0
        and len(new_rows) == 1
    )
    print(json.dumps({"ok": ok, **side}, indent=2))
    if not ok:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="List or call jarvis-trading MCP tools")
    parser.add_argument("command", choices=("doctor", "drive"))
    parser.add_argument("--url", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--access-log", default="")
    parser.add_argument("--tool", default="get_crash_risk")
    parser.add_argument("--args", default="{}")
    args = parser.parse_args()
    _require_loopback(args.url)
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    access_log = Path(args.access_log) if args.access_log else evidence / "paper-access.jsonl"
    if args.command == "doctor":
        doctor(args.url, evidence, access_log)
        return
    drive(args.url, evidence, access_log, args.tool, json.loads(args.args))


if __name__ == "__main__":
    main()
