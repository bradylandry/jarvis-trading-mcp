#!/usr/bin/env python3
"""Start the real server (`python -m friend_mcp.server`) once per sign-in setting combination.

A half-set combination must refuse to start: nonzero exit, never "Uvicorn running", no
Python traceback, and a "refusing to start" line that names the missing setting.
Fully unset on 127.0.0.1 must start and answer list_tools with the seven tools.
Fully unset on 0.0.0.0 must hit the existing fail-closed guard.

Every child gets placeholder values only, JARVIS_TRADING_API on loopback, both cases of
HTTP_PROXY, HTTPS_PROXY, and ALL_PROXY pointed at a closed loopback port with loopback no_proxy,
and no Azure credential settings (managed identity points at the same dead port), so nothing it
does can leave the machine. The full
four-setting sign-in case is not run here: it builds the real AzureProvider.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse
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
BLACKHOLE = "http://127.0.0.1:9"
PROXY_KEYS = ("http_proxy", "https_proxy", "all_proxy", "no_proxy")


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
    # Drop inherited sign-in, token, Azure credential, and proxy settings of either case.
    # Python prefers lowercase proxy names, so both cases are set explicitly below.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("AUTH_", "JARVIS_", "KEY_VAULT", "ALLOW_", "PUBLIC_BASE_URL",
                                "AZURE_", "IDENTITY_", "MSI_"))
           and k.lower() not in PROXY_KEYS}
    env.update(
        PYTHONUNBUFFERED="1",
        JARVIS_TRADING_TOKEN="paper",
        JARVIS_TRADING_API=api,
        HOST="127.0.0.1",
        PORT=str(port),
        MSI_ENDPOINT=BLACKHOLE,
        IDENTITY_ENDPOINT=BLACKHOLE,
    )
    for key in PROXY_KEYS:
        value = "127.0.0.1,localhost" if key == "no_proxy" else BLACKHOLE
        env[key] = value
        env[key.upper()] = value
    env.update(extra)
    return env


async def list_tools(port: int) -> list[str]:
    async with Client(f"http://127.0.0.1:{port}/mcp", timeout=20) as client:
        return [tool.name for tool in await client.list_tools()]


def stop_child(proc: subprocess.Popen) -> None:
    """SIGTERM then SIGKILL our own child's process group (it was started in a new session)."""
    if proc.poll() is not None:
        return
    for sig, wait_s in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=wait_s)
            return
        except subprocess.TimeoutExpired:
            continue


def run_case(case: dict, python: str, repo: Path, port: int, api: str, logdir: Path,
             timeout_s: float) -> dict:
    log_path = logdir / f"signin-{case['name']}.log"
    pid_path = logdir / "signin.pid"
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen([python, "-m", "friend_mcp.server"], cwd=repo,
                                env=child_env(port, api, case["env"]),
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    # Cleanup can reap this child from signin.pid if the matrix itself is killed.
    pid_path.write_text(f"{proc.pid}\n")
    # Any bind counts as started, including 0.0.0.0, so a regressed guard is caught at once
    # and never left serving on all interfaces until the timeout.
    ready = "Uvicorn running on http://"
    deadline = time.monotonic() + timeout_s
    served = False
    tools: list[str] = []
    try:
        while time.monotonic() < deadline:
            if ready in log_path.read_text(encoding="utf-8", errors="replace"):
                served = True
                break
            if proc.poll() is not None:
                break
            time.sleep(0.2)
        # Only an expected local serve is exercised; anything else that started is stopped now.
        if served and case["expect"] == "serve":
            try:
                tools = asyncio.run(list_tools(port))
            except Exception as exc:  # noqa: BLE001 - recorded as evidence
                tools = [f"list_tools failed: {type(exc).__name__}"]
    finally:
        still_running = proc.poll() is None
        stop_child(proc)
        if proc.poll() is not None:
            pid_path.unlink(missing_ok=True)
    exit_code = None if (served or still_running) else proc.returncode
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
    api = urlparse(args.api)
    if (api.scheme != "http" or api.hostname != "127.0.0.1" or api.username or api.password
            or not str(api.port or "").isdigit()):
        raise SystemExit("refusing non-loopback JARVIS_TRADING_API")
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", args.port))
    except OSError:
        raise SystemExit(f"port busy: {args.port}; export another SIGNIN_PORT") from None
    finally:
        sock.close()
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
