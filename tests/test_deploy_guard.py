"""deploy.sh stops before any az call when sign-in settings are half set. az is a stub on PATH."""
import os
import stat
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET = "fake-client-secret-value-0123"


class DeployGuardTests(unittest.TestCase):
    def run_deploy(self, extra):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "az-calls.log")
            az = os.path.join(d, "az")
            with open(az, "w") as f:
                # records that az was reached (no arguments, so no secret lands in the log) and stops the script
                f.write(f"#!/bin/sh\necho called >> '{log}'\nexit 97\n")
            os.chmod(az, os.stat(az).st_mode | stat.S_IEXEC)
            env = {k: v for k, v in os.environ.items() if not k.startswith("AUTH_")}
            env["PATH"] = d + os.pathsep + env.get("PATH", "")
            env.update(extra)
            r = subprocess.run(["bash", os.path.join(REPO, "deploy.sh")], cwd=REPO, env=env,
                               capture_output=True, text=True, timeout=60)
            called = os.path.exists(log)
        return r, called

    def test_client_id_without_secret_stops_before_az(self):
        r, called = self.run_deploy({"AUTH_CLIENT_ID": "id", "AUTH_TENANT_ID": "tenant",
                                     "AUTH_CLIENT_SECRET": ""})
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(called, "az was called with an empty AUTH_CLIENT_SECRET")
        self.assertIn("AUTH_CLIENT_SECRET", r.stderr)

    def test_client_id_with_whitespace_secret_stops_before_az(self):
        r, called = self.run_deploy({"AUTH_CLIENT_ID": "id", "AUTH_TENANT_ID": "tenant",
                                     "AUTH_CLIENT_SECRET": "  "})
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(called)

    def test_client_id_without_tenant_stops_before_az(self):
        r, called = self.run_deploy({"AUTH_CLIENT_ID": "id", "AUTH_CLIENT_SECRET": SECRET})
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(called)
        self.assertIn("AUTH_TENANT_ID", r.stderr)

    def test_full_settings_reach_az(self):
        r, called = self.run_deploy({"AUTH_CLIENT_ID": "id", "AUTH_TENANT_ID": "tenant",
                                     "AUTH_CLIENT_SECRET": SECRET})
        self.assertTrue(called)
        self.assertNotIn(SECRET, r.stdout + r.stderr)

    def test_first_deploy_without_auth_reaches_az(self):
        r, called = self.run_deploy({})
        self.assertTrue(called)


if __name__ == "__main__":
    unittest.main()
