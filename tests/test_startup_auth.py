"""Startup refuses half-set sign-in. Runs the server module in a subprocess with mcp.run stubbed."""
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET = "fake-client-secret-value-0123"

CODE = (
    "import friend_mcp.server as s\n"
    "s.mcp.run = lambda **k: print('WOULD SERVE')\n"
    "s.main()\n"
)


def start(extra):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("AUTH_", "JARVIS_", "KEY_VAULT", "ALLOW_"))}
    env.update(
        PYTHONPATH=REPO,
        JARVIS_TRADING_TOKEN="fake",
        JARVIS_TRADING_API="http://127.0.0.1:9",
        HTTPS_PROXY="http://127.0.0.1:9",
        HTTP_PROXY="http://127.0.0.1:9",
        FASTMCP_HOME=os.path.join(REPO, ".test-fastmcp-home"),
        HOST="0.0.0.0",
    )
    env.update(extra)
    return subprocess.run([sys.executable, "-c", CODE], env=env, capture_output=True,
                          text=True, timeout=120)


SIGNIN = {
    "AUTH_CLIENT_ID": "00000000-0000-0000-0000-000000000001",
    "AUTH_TENANT_ID": "00000000-0000-0000-0000-000000000002",
    "PUBLIC_BASE_URL": "http://127.0.0.1:18080",
}


class StartupAuthTests(unittest.TestCase):
    def assertRefused(self, r):
        out = r.stdout + r.stderr
        self.assertNotEqual(r.returncode, 0, out)
        self.assertNotIn("WOULD SERVE", out)
        self.assertIn("AUTH_CLIENT_SECRET", out)

    def test_empty_secret_refuses(self):
        self.assertRefused(start({**SIGNIN, "AUTH_CLIENT_SECRET": ""}))

    def test_whitespace_secret_refuses(self):
        self.assertRefused(start({**SIGNIN, "AUTH_CLIENT_SECRET": "   "}))

    def test_missing_secret_refuses_with_clear_message(self):
        self.assertRefused(start(SIGNIN))

    def test_real_secret_starts_and_is_not_printed(self):
        r = start({**SIGNIN, "AUTH_CLIENT_SECRET": SECRET})
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("WOULD SERVE", out)
        self.assertNotIn(SECRET, out)


class HalfSetSignInTests(unittest.TestCase):
    """Missing tenant or URL, or sign-in settings without a client id, refuse with a clear line."""

    def assertRefusedNaming(self, r, name):
        out = r.stdout + r.stderr
        self.assertNotEqual(r.returncode, 0, out)
        self.assertNotIn("WOULD SERVE", out)
        self.assertNotIn("Traceback", out)
        self.assertNotIn(SECRET, out)
        refusal = [l for l in out.splitlines() if l.startswith("refusing to start")]
        self.assertTrue(refusal, out)
        self.assertIn(name, refusal[0])

    def test_missing_tenant_refuses(self):
        env = {**SIGNIN, "AUTH_CLIENT_SECRET": SECRET}
        del env["AUTH_TENANT_ID"]
        self.assertRefusedNaming(start(env), "AUTH_TENANT_ID")

    def test_blank_tenant_refuses(self):
        r = start({**SIGNIN, "AUTH_CLIENT_SECRET": SECRET, "AUTH_TENANT_ID": "  "})
        self.assertRefusedNaming(r, "AUTH_TENANT_ID")

    def test_missing_public_base_url_refuses(self):
        env = {**SIGNIN, "AUTH_CLIENT_SECRET": SECRET}
        del env["PUBLIC_BASE_URL"]
        self.assertRefusedNaming(start(env), "PUBLIC_BASE_URL")

    def test_missing_both_names_both(self):
        r = start({"AUTH_CLIENT_ID": SIGNIN["AUTH_CLIENT_ID"], "AUTH_CLIENT_SECRET": SECRET})
        self.assertRefusedNaming(r, "AUTH_TENANT_ID")
        self.assertRefusedNaming(r, "PUBLIC_BASE_URL")

    # Loopback bind, so the older public-bind guard cannot be what refuses.
    def test_secret_without_client_id_refuses_on_loopback(self):
        r = start({"AUTH_CLIENT_SECRET": SECRET, "HOST": "127.0.0.1"})
        self.assertRefusedNaming(r, "AUTH_CLIENT_ID")

    def test_tenant_and_url_without_client_id_refuses_on_loopback(self):
        r = start({"AUTH_TENANT_ID": SIGNIN["AUTH_TENANT_ID"],
                   "PUBLIC_BASE_URL": SIGNIN["PUBLIC_BASE_URL"], "HOST": "127.0.0.1"})
        self.assertRefusedNaming(r, "AUTH_CLIENT_ID")

    def test_blank_client_id_with_secret_refuses_on_loopback(self):
        r = start({"AUTH_CLIENT_ID": "  ", "AUTH_CLIENT_SECRET": SECRET, "HOST": "127.0.0.1"})
        self.assertRefusedNaming(r, "AUTH_CLIENT_ID")

    def test_all_unset_loopback_still_serves(self):
        r = start({"HOST": "127.0.0.1"})
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("WOULD SERVE", out)

    def test_all_blank_loopback_still_serves(self):
        r = start({k: " " for k in ("AUTH_CLIENT_SECRET", "AUTH_TENANT_ID", "PUBLIC_BASE_URL")}
                  | {"AUTH_CLIENT_ID": "", "HOST": "127.0.0.1"})
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("WOULD SERVE", out)

    def test_all_unset_public_bind_still_refuses(self):
        r = start({})
        out = r.stdout + r.stderr
        self.assertNotEqual(r.returncode, 0, out)
        self.assertNotIn("WOULD SERVE", out)
        self.assertIn("refusing to start remote HTTP transport", out)


if __name__ == "__main__":
    unittest.main()
