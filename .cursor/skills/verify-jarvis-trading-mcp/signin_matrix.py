#!/usr/bin/env python3
"""Start the real server (`python -m friend_mcp.server`) once per sign-in setting combination.

A half-set combination must refuse to start: nonzero exit, never "Uvicorn running", no
Python traceback, and a "refusing to start" line that names the missing setting.
Fully unset on 127.0.0.1 must start and answer list_tools with the seven tools.
Fully unset on 0.0.0.0 must hit the existing fail-closed guard.

Every child gets placeholder values only, JARVIS_TRADING_API on loopback, and HTTP(S)_PROXY
pointed at a closed loopback port, so nothing it does can leave the machine. The full
four-setting sign-in case is not run here: it builds the real AzureProvider.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from fastmcp import Client

EXPECTED_TOOLS = {
    "scan_universe", "get_thesis", "get_fit_score", "get_crash_risk",
    "get_earnings_analysis", "get_geopolitical", "get_iv",
}
CLIENT_ID = "00000000-0000-0000-0000-00000000c1d0"
TENANT_ID = "00000000-0000-0000-0000-000000007e17"
SECRET = "placeholder-client-secret-x9Q4"  # not a real secret; also leak-checked below
SIGNIN_KEYS = ("AUTH_CLIENT_ID", "AUTH_CLIENT_SECRET", "AUTH_TENANT_ID", "PUBLIC_BASE_URL")


def cases(port: int) -> list[dict]:
    url = f"http://127.0.0.1:{port}"
    return [
        {"name": "client-id-only", "env": {"AUTH_CLIENT_ID": CLIENT_ID},
         "expect": "refuse", "names": "AUTH_CLIENT_SECRET"},
        {"name": "all-but-secret",
         "env": {"AUTH_CLIENT_ID": CLIENT_ID, "AUTH_TENANT_ID": TENANT_ID, "PUBLIC_BASE_URL": url},
         "expect": "refuse", "names": "AUTH_CLIENT_SECRET"},
        {"name": "whitespace-secret",
         "env": {"AUTH_CLIENT_ID": CLIENT_ID, "AUTH_CLIENT_SECRET": "   ",
                 "AUTH_TENANT_ID": TENANT_ID, "PUBLIC_BASE_URL": url},
         "expect": "refuse", "names": "AUTH_CLIENT_SECRET"},
        {"name": "id-and-secret-no-tenant",
         "env": {"AUTH_CLIENT_ID": CLIENT_ID, "AUTH_CLIENT_SECRET": SECRET},
         "expect": "refuse", "names": "AUTH_TENANT_ID"},
        {"name": "all-but-public-base-url",
         "env": {"AUTH_CLIENT_ID": CLIENT_ID, "AUTH_CLIENT_SECRET": SECRET, "AUTH_TENANT_ID": TENANT_ID},
         "expect": "refuse", "names": "PUBLIC_BASE_URL"},
        {"name": "secret-only", "env": {"AUTH_CLIENT_SECRET": SECRET},
         "expect": "refuse", "names": "AUTH_CLIENT_ID"},
        {"name": "tenant-and-url-only",
         "env": {"AUTH_TENANT_ID": TENANT_ID, "PUBLIC_BASE_URL": url},
         "expect": "refuse", "names": "AUTH_CLIENT_ID"},
        {"name": "all-unset-loopback", "env": {}, "expect": "serve"},
        {"name": "all-unset-public-bind", "env": {"HOST": "0.0.0.0"},
         "expect": "refuse", "names": "AUTH_CLIENT_ID"},
    ]


def child_env(port: int, api: str, extra: dict) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("AUTH_", "JARVIS_", "KEY_VAULT", "ALLOW_", "PUBLIC_BASE_URL"))}
    env.update(
        PYTHONUNBUFFERED="1",
        JARVIS_TRADING_TOKEN="paper",
        JARVIS_TRADING_API=api,
        HOST="127.0.0.1",
        PORT=str(port),
        HTTP_PROXY="http://127.0.0.1:9",
        HTTPS_PROXY="http://127.0.0.1:9",
        NO_PROXY="127.0.0.1,localhost",
    )
    env.update(extra)
    return env


async def list_tools(port: int) -> list[str]:
    async with Client(f"http://127.0.0.1:{port}/mcp", timeout=20) as client:
        return [tool.name for tool in await client.list_tools()]


def run_case(case: dict, python: str, repo: Path, port: int, api: str, logdir: Path,
             timeout_s: float) -> dict:
    log_path = logdir / f"signin-{case['name']}.log"
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen([python, "-m", "friend_mcp.server"], cwd=repo,
                                env=child_env(port, api, case["env"]),
                                stdout=log, stderr=subprocess.STDOUT)
    ready = f"Uvicorn running on http://127.0.0.1:{port}"
    deadline = time.monotonic() + timeout_s
    served = False
    while time.monotonic() < deadline:
        if ready in log_path.read_text(encoding="utf-8", errors="replace"):
            served = True
            break
        if proc.poll() is not None:
            break
        time.sleep(0.2)
    tools: list[str] = []
    if served:
        try:
            tools = asyncio.run(list_tools(port))
        except Exception as exc:  # noqa: BLE001 - recorded as evidence
            tools = [f"list_tools failed: {type(exc).__name__}"]
    if proc.poll() is None:
        proc.terminate()  # our own child, by handle
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        exit_code = None if served else proc.returncode
    else:
        exit_code = proc.returncode
    out = log_path.read_text(encoding="utf-8", errors="replace")
    refusal = next((line for line in out.splitlines() if line.startswith("refusing to start")), "")
    record = {
        "name": case["name"],
        "settings_set": sorted(k for k in case["env"] if k in SIGNIN_KEYS),
        "host": case["env"].get("HOST", "127.0.0.1"),
        "expect": case["expect"],
        "served": served,
        "exit_code": exit_code,
        "traceback": "Traceback (most recent call last)" in out,
        "refusal_line": refusal,
        "last_line": out.strip().splitlines()[-1] if out.strip() else "",
        "tools": sorted(tools),
        "secret_in_output": SECRET in out,
        "log": str(log_path),
    }
    if case["expect"] == "serve":
        record["ok"] = served and set(tools) == EXPECTED_TOOLS and not record["secret_in_output"]
    else:
        record["names_setting"] = case["names"] in refusal
        record["ok"] = (
            not served
            and exit_code not in (0, None)
            and not record["traceback"]
            and bool(refusal)
            and record["names_setting"]
            and not record["secret_in_output"]
        )
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="Half-set sign-in startup matrix")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--port", type=int, required=True, help="free loopback port for the child")
    parser.add_argument("--api", required=True, help="loopback JARVIS_TRADING_API")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if not args.api.startswith("http://127.0.0.1:"):
        raise SystemExit("refusing non-loopback JARVIS_TRADING_API")
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    results = [run_case(case, args.python, Path(args.repo), args.port, args.api, evidence,
                        args.timeout) for case in cases(args.port)]
    payload = {"ok": all(r["ok"] for r in results), "cases": results}
    (evidence / "signin-matrix.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for r in results:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['name']}: served={r['served']} "
              f"exit={r['exit_code']} traceback={r['traceback']} "
              f"line={r['refusal_line'] or r['last_line']!r}")
    print("signin matrix ok" if payload["ok"] else "signin matrix FAILED")
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
