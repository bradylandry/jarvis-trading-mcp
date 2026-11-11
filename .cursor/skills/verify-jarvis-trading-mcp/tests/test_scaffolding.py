"""Unit tests for the verify skill's own scaffolding: the fake Key Vault guard and leakcheck.

Run from the repository root:
  .venv/bin/python -m unittest discover -s .cursor/skills/verify-jarvis-trading-mcp/tests -v
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "fake_kv"))
sys.path.insert(0, str(SKILL_DIR))

import mcp_client  # noqa: E402
from azure.keyvault.secrets import SecretClient  # noqa: E402  (the fake, first on sys.path)

TOKEN = "placeholder-unit-test-token-T3ST"


class FakeVaultTest(unittest.TestCase):
    def test_loads_the_fake(self):
        self.assertTrue(SecretClient.fake)
        self.assertTrue(str(SKILL_DIR / "fake_kv") in sys.modules["azure"].__file__)

    def test_refuses_non_invalid_vault(self):
        for url in ("https://real-vault.vault.azure.net/", "https://fake.invalid.example.com/",
                    "http://127.0.0.1/", ""):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                SecretClient(url)

    def test_reads_file_and_logs_last4_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = Path(tmp, "kv-secret")
            secret.write_text(TOKEN + "\n", encoding="utf-8")
            log = Path(tmp, "reads.jsonl")
            env = {"VERIFY_FAKE_KV_FILE": str(secret), "VERIFY_FAKE_KV_LOG": str(log)}
            with mock.patch.dict(os.environ, env):
                value = SecretClient("https://fake-kv.invalid/").get_secret("name").value
            self.assertEqual(value, TOKEN)
            row = json.loads(log.read_text(encoding="utf-8"))
            self.assertEqual(row["value_last4"], "T3ST")
            self.assertNotIn(TOKEN, log.read_text(encoding="utf-8"))


class LeakcheckTest(unittest.TestCase):
    def run_leakcheck(self, evidence: Path, tokens: list[str]) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                mcp_client.leakcheck(evidence, tokens)
            except SystemExit as exc:
                return 1 if exc.code is None else (exc.code if isinstance(exc.code, int) else 2)
        return 0

    def test_no_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "server.log").write_text("token last4 T3ST\n", encoding="utf-8")
            self.assertEqual(self.run_leakcheck(Path(tmp), [TOKEN]), 0)
            report = json.loads(Path(tmp, "leakcheck.json").read_text(encoding="utf-8"))
            self.assertEqual(report["hits"], [])

    def test_hit_in_nested_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "sub").mkdir()
            Path(tmp, "sub", "signin-x.log").write_text(f"oops {TOKEN}\n", encoding="utf-8")
            self.assertNotEqual(self.run_leakcheck(Path(tmp), [TOKEN]), 0)
            report = json.loads(Path(tmp, "leakcheck.json").read_text(encoding="utf-8"))
            self.assertEqual(len(report["hits"]), 1)
            self.assertNotIn(TOKEN, json.dumps(report))

    def test_refuses_short_or_empty_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.log").write_text("x\n", encoding="utf-8")
            for token in ("", "abc", "1234567"):
                with self.subTest(token=token):
                    self.assertNotEqual(self.run_leakcheck(Path(tmp), [token]), 0)
            self.assertFalse(Path(tmp, "leakcheck.json").exists())


if __name__ == "__main__":
    unittest.main()
