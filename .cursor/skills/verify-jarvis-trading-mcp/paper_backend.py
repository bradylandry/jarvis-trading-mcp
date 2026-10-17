#!/usr/bin/env python3
"""Loopback paper stand-in for the trading research API.

Speaks the seven GET paths friend_mcp.server calls. Every other path and
every non-GET method is rejected. Nothing here places an order or dials out.
"""
from __future__ import annotations

import argparse
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_log_lock = threading.Lock()

EXPECTED_TOKEN = "paper"
ALLOWED_PATHS = {
    "/api/options/scan/universe",
    "/api/options/thesis",
    "/api/screener",
    "/api/macro/crash-risk",
    "/api/macro/earnings-analyses",
    "/api/macro/political",
    "/api/options/iv",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fixture(path: str, query: dict[str, list[str]]) -> dict | list:
    echo = {key: values[-1] for key, values in query.items()}
    base = {"paper": True, "source": "paper-backend", "orders_placed": 0, "echo": echo}
    if path == "/api/options/scan/universe":
        return [{
            **base,
            "ticker": "PAPER",
            "fit_score": 7.0,
            "opt_type": echo.get("type", "call"),
            "mode": echo.get("mode", "plan_b"),
        }]
    if path == "/api/options/thesis":
        return {
            **base,
            "ticker": echo.get("ticker", "PAPER"),
            "verdict": "PAPER",
            "bull_case": "paper fixture",
            "bear_case": "paper fixture",
            "exit_plan": "none — paper fixture, no position",
        }
    if path == "/api/screener":
        return {**base, "ticker": echo.get("tickers", "PAPER"), "fit_score": 6.0}
    if path == "/api/macro/crash-risk":
        return {
            **base,
            "score": 3.5,
            "components": {
                "yield_curve": 2,
                "breadth": 4,
                "vix_term_structure": 3,
                "credit_spreads": 3,
                "insider_selling": 5,
                "earnings_sentiment": 4,
            },
        }
    if path == "/api/macro/earnings-analyses":
        return {
            **base,
            "ticker": echo.get("ticker", "PAPER"),
            "verdict": "HOLD",
            "conviction": "LOW",
            "verdict_thesis": "paper fixture",
        }
    if path == "/api/macro/political":
        return {
            **base,
            "regions": {
                "ukraine": 2,
                "iran": 3,
                "china_taiwan": 2,
                "tariff": 4,
                "fed_hawkishness": 3,
            },
        }
    if path == "/api/options/iv":
        return {
            **base,
            "ticker": echo.get("ticker", "PAPER"),
            "dte": echo.get("dte", "30"),
            "atm_iv": 0.25,
            "realized_vol_30d": 0.22,
            "iv_rv_ratio": 1.14,
        }
    raise KeyError(path)


class PaperHandler(BaseHTTPRequestHandler):
    access_log_path: str = ""
    expected_token: str = EXPECTED_TOKEN

    def log_message(self, fmt: str, *args) -> None:
        # Access lines go to the JSONL file, not stderr.
        return

    def _log(self, status: int) -> None:
        parsed = urlparse(self.path)
        token = self.headers.get("X-API-Token", "")
        record = {
            "ts": _utc_now(),
            "method": self.command,
            "path": parsed.path,
            "query": {k: v[-1] for k, v in parse_qs(parsed.query).items()},
            "token_present": bool(token),
            "token_last4": token[-4:] if token else "",
            "status": status,
        }
        line = json.dumps(record, sort_keys=True) + "\n"
        with _log_lock:
            with open(self.access_log_path, "a", encoding="utf-8") as handle:
                handle.write(line)

    def _send(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self._log(status)

    def _reject(self, status: int, message: str) -> None:
        self._send(status, {"paper": True, "orders_placed": 0, "error": message})

    def _dispatch(self) -> None:
        if self.command != "GET":
            self._reject(405, "paper backend accepts GET only; no orders")
            return
        parsed = urlparse(self.path)
        if parsed.path not in ALLOWED_PATHS:
            self._reject(404, "unknown path; paper backend has no order routes")
            return
        token = self.headers.get("X-API-Token", "")
        if token != self.expected_token:
            self._reject(401, "paper token rejected")
            return
        self._send(200, _fixture(parsed.path, parse_qs(parsed.query)))

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch()

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch()

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch()

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch()


def main() -> None:
    parser = argparse.ArgumentParser(description="Loopback paper trading-research API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--access-log", required=True)
    parser.add_argument("--token", default=EXPECTED_TOKEN)
    args = parser.parse_args()
    if args.host != "127.0.0.1":
        raise SystemExit("paper backend binds 127.0.0.1 only")
    PaperHandler.access_log_path = args.access_log
    PaperHandler.expected_token = args.token
    open(args.access_log, "a", encoding="utf-8").close()
    server = ThreadingHTTPServer((args.host, args.port), PaperHandler)
    print(f"paper backend ready http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
