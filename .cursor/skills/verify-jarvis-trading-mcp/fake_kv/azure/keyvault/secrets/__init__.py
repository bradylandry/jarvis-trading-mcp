"""Fake azure.keyvault.secrets backed by one local file.

VERIFY_FAKE_KV_FILE  file holding the current secret value (rewrite it to rotate)
VERIFY_FAKE_KV_LOG   JSONL; one row per get_secret with the last 4 characters only
"""
from __future__ import annotations

import json
import os
import threading
import types
from datetime import datetime, timezone
from urllib.parse import urlparse

_lock = threading.Lock()


class SecretClient:
    fake = True

    def __init__(self, vault_url: str, credential=None, **kwargs):
        host = urlparse(vault_url).hostname or ""
        if not host.endswith(".invalid"):
            raise RuntimeError("fake Key Vault only accepts a *.invalid KEY_VAULT_URL")
        self.vault_host = host

    def get_secret(self, name: str):
        path = os.environ["VERIFY_FAKE_KV_FILE"]
        with open(path, encoding="utf-8") as handle:
            value = handle.read().strip()
        row = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "vault_host": self.vault_host,
            "name": name,
            "value_last4": value[-4:] if value else "",
        }
        log = os.environ.get("VERIFY_FAKE_KV_LOG")
        if log:
            with _lock, open(log, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        return types.SimpleNamespace(name=name, value=value)
