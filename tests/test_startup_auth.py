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

    def test_refusal_does_not_print_secret(self):
        r = start({**SIGNIN, "AUTH_CLIENT_SECRET": "  "})
        self.assertNotIn(SECRET, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
