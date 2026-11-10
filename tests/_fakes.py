"""In-memory fakes for Key Vault and the trading API. Nothing here touches the network."""
import importlib
import os
import sys
import types

import httpx

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

FAKE_API = "http://fake-trading.invalid"


class World:
    """What the fake Key Vault holds and which token the fake trading API accepts."""

    def __init__(self):
        self.vault = "tok-one-aaaaaaaa"
        self.accepted = "tok-one-aaaaaaaa"
        self.vault_up = True
        self.vault_reads = 0
        self.status_override = None  # force a status, e.g. 500
        self.sent = []  # tokens sent upstream, in order


class Resp:
    def __init__(self, code):
        self.status_code = code

    def json(self):
        return {"composite": 4.2}


def install(world, env=None):
    """Point friend_mcp.server at the fakes and (re)import it, like a fresh process start."""

    class FakeSecretClient:
        def __init__(self, vault_url, credential):
            pass

        def get_secret(self, name):
            world.vault_reads += 1
            if not world.vault_up:
                raise RuntimeError("fake: vault unreachable")
            return types.SimpleNamespace(value=world.vault)

    ai = types.ModuleType("azure.identity")
    ai.ManagedIdentityCredential = lambda: object()
    ak = types.ModuleType("azure.keyvault.secrets")
    ak.SecretClient = FakeSecretClient
    sys.modules["azure.identity"] = ai
    sys.modules["azure.keyvault.secrets"] = ak

    def fake_get(url, params=None, headers=None, timeout=None):
        if not url.startswith(FAKE_API + "/"):
            raise AssertionError(f"unexpected upstream URL {url}")
        tok = headers["X-API-Token"]
        world.sent.append(tok)
        if world.status_override is not None:
            return Resp(world.status_override)
        return Resp(200 if tok == world.accepted else 401)

    httpx.get = fake_get

    for k in ("JARVIS_TRADING_TOKEN", "AUTH_CLIENT_ID", "AUTH_CLIENT_SECRET"):
        os.environ.pop(k, None)
    os.environ.update(
        KEY_VAULT_URL="https://fake-vault.invalid/",
        JARVIS_TOKEN_SECRET_NAME="fake-secret",
        JARVIS_TRADING_API=FAKE_API,
        JARVIS_TRADING_MAX_CALLS_PER_MIN="1000",
    )
    os.environ.update(env or {})
    sys.modules.pop("friend_mcp.server", None)
    return importlib.import_module("friend_mcp.server")
