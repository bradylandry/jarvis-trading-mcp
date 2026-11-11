#!/usr/bin/env python3
"""MCP client checks for the verify skill.

doctor: list tools. Does not call the research API.
drive: call one tool and check the upstream rows the paper backend logged for it.
       Default expectation is one GET, status 200, token last4 "aper". --expect-rows,
       --expect-error, and --expect-kv-reads describe the 401 reread journeys.
leakcheck: fail if any full token value appears in any evidence file.
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
# An empty or very short --token would match almost any file.
MIN_TOKEN_LEN = 8


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
        # Keep tool errors as results so the error journeys can record them.
        return await client.call_tool(name, arguments, raise_on_error=False)


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


def _suffix(label: str) -> str:
    return f"-{label}" if label else ""


def doctor(url: str, evidence: Path, access_log: Path, label: str = "") -> None:
    if not access_log.exists():
        raise SystemExit(f"missing paper access log: {access_log}")
    before = _read_jsonl(access_log)
    tools = asyncio.run(_list_tools(url))
    after = _read_jsonl(access_log)
    names = [tool["name"] for tool in tools]
    payload = {"count": len(tools), "tools": tools, "upstream_requests_added": len(after) - len(before)}
    _write(evidence / f"tools{_suffix(label)}.json", payload)
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


DEFAULT_ROWS = [{"status": 200, "token_last4": "aper"}]


def drive(url: str, evidence: Path, access_log: Path, tool: str, arguments: dict,
          label: str = "", expect_rows: list[dict] | None = None, expect_error: str = "",
          kv_log: Path | None = None, expect_kv_reads: int | None = None) -> None:
    if tool not in UPSTREAM_PATH:
        raise SystemExit(f"unknown tool {tool}")
    if not access_log.exists():
        raise SystemExit(f"missing paper access log: {access_log}")
    if expect_kv_reads is not None and kv_log is None:
        raise SystemExit("--expect-kv-reads needs --kv-log")
    expect_rows = expect_rows if expect_rows is not None else DEFAULT_ROWS
    before = _read_jsonl(access_log)
    kv_before = _read_jsonl(kv_log) if kv_log else []
    result = asyncio.run(_call_tool(url, tool, arguments))
    after = _read_jsonl(access_log)
    kv_new = (_read_jsonl(kv_log) if kv_log else [])[len(kv_before):]
    new_rows = after[len(before):]
    texts = _content_text(result)
    call_payload = {
        "tool": tool,
        "label": label,
        "arguments": arguments,
        "is_error": result.is_error,
        "structured_content": _jsonable(result.structured_content),
        "data": _jsonable(result.data),
        "text": texts,
    }
    _write(evidence / f"call-{tool}{_suffix(label)}.json", call_payload)
    expected_path = UPSTREAM_PATH[tool]
    paths_ok = bool(new_rows) and all(row.get("path") == expected_path for row in new_rows)
    methods_ok = bool(new_rows) and all(row.get("method") == "GET" for row in new_rows)
    seen = [{"status": row.get("status"), "token_last4": row.get("token_last4")} for row in new_rows]
    rows_ok = seen == expect_rows
    if expect_error:
        body = None
        paper = None
        orders = None
        outcome_ok = result.is_error and any(expect_error in text for text in texts)
    else:
        body = _paper_body(result)
        paper = body is not None and body.get("paper") is True
        orders = body.get("orders_placed") if body else None
        outcome_ok = not result.is_error and paper and orders == 0
    kv_ok = expect_kv_reads is None or len(kv_new) == expect_kv_reads
    side = {
        "tool": tool,
        "label": label,
        "upstream_path": expected_path,
        "new_requests": new_rows,
        "expected_rows": expect_rows,
        "rows_matched": rows_ok,
        "all_get": methods_ok,
        "path_matched": paths_ok,
        "is_error": result.is_error,
        "expected_error": expect_error or None,
        "outcome_matched": outcome_ok,
        "kv_reads": kv_new if kv_log else None,
        "expected_kv_reads": expect_kv_reads,
        "paper": paper,
        "orders_placed": orders,
    }
    _write(evidence / f"side-effects{_suffix(label)}.json", side)
    ok = methods_ok and paths_ok and rows_ok and outcome_ok and kv_ok
    print(json.dumps({"ok": ok, **side}, indent=2))
    if not ok:
        raise SystemExit(1)


def leakcheck(evidence: Path, tokens: list[str]) -> None:
    """Every evidence file must be free of each full token value."""
    if any(len(token) < MIN_TOKEN_LEN for token in tokens):
        raise SystemExit(f"leakcheck refuses tokens under {MIN_TOKEN_LEN} characters")
    hits = []
    scanned = 0
    for path in sorted(evidence.rglob("*")):
        if not path.is_file():
            continue
        scanned += 1
        data = path.read_bytes()
        for index, token in enumerate(tokens):
            if token.encode() in data:
                hits.append({"file": str(path), "token_index": index, "token_last4": token[-4:]})
    payload = {"files_scanned": scanned, "tokens_checked": [t[-4:] for t in tokens], "hits": hits}
    _write(evidence / "leakcheck.json", payload)
    print(json.dumps({"ok": not hits, **payload}, indent=2))
    if hits or not scanned:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="List or call jarvis-trading MCP tools")
    parser.add_argument("command", choices=("doctor", "drive", "leakcheck"))
    parser.add_argument("--url", default="")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--access-log", default="")
    parser.add_argument("--tool", default="get_crash_risk")
    parser.add_argument("--args", default="{}")
    parser.add_argument("--label", default="", help="suffix for call-/side-effects-/tools- files")
    parser.add_argument("--expect-rows", default="",
                        help='JSON list of {"status", "token_last4"}, one per upstream row')
    parser.add_argument("--expect-error", default="", help="tool must error with this text")
    parser.add_argument("--kv-log", default="", help="fake Key Vault read log (JSONL)")
    parser.add_argument("--expect-kv-reads", type=int, default=None)
    parser.add_argument("--token", action="append", default=[], help="leakcheck: a full token value")
    args = parser.parse_args()
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    if args.command == "leakcheck":
        if not args.token:
            raise SystemExit("leakcheck needs at least one --token")
        leakcheck(evidence, args.token)
        return
    _require_loopback(args.url)
    access_log = Path(args.access_log) if args.access_log else evidence / "paper-access.jsonl"
    if args.command == "doctor":
        doctor(args.url, evidence, access_log, args.label)
        return
    drive(
        args.url, evidence, access_log, args.tool, json.loads(args.args),
        label=args.label,
        expect_rows=json.loads(args.expect_rows) if args.expect_rows else None,
        expect_error=args.expect_error,
        kv_log=Path(args.kv_log) if args.kv_log else None,
        expect_kv_reads=args.expect_kv_reads,
    )


if __name__ == "__main__":
    main()
