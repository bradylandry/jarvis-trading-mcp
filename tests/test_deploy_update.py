"""deploy.sh keeps env, image, registry, and the Key Vault grant. az is a stub on PATH."""
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET = "fake-client-secret-value-0123"
VAULT_NAME = "kv-jarvis-lab2"
IMAGE_SUFFIX = ".azurecr.io/jarvis-trading-mcp:latest"

AZ_STUB = textwrap.dedent(
    r"""
    #!/usr/bin/env python3
    import os, sys
    log = os.environ["AZ_LOG"]
    state = os.environ["AZ_STATE"]
    redact = os.environ.get("AZ_REDACT", "")
    args = sys.argv[1:]
    safe = []
    for a in args:
        if redact and redact in a:
            a = a.replace(redact, "***")
        safe.append(a)
    with open(log, "a") as f:
        f.write("\t".join(safe) + "\n")
    cmd = args[0] if args else ""
    sub = args[1] if len(args) > 1 else ""

    def flag(name):
        if name not in args:
            return ""
        i = args.index(name)
        return args[i + 1] if i + 1 < len(args) else ""

    def created():
        if not os.path.exists(state):
            return set()
        return set(open(state).read().split())

    if cmd == "acr" and sub == "show":
        sys.exit(0 if flag("-n") in created() else 1)
    if cmd == "acr" and sub == "create":
        name = flag("-n")
        have = created()
        if name in have:
            sys.stderr.write("registry already exists\n")
            sys.exit(1)
        with open(state, "a") as f:
            f.write(name + "\n")
        sys.exit(0)
    if cmd == "containerapp" and sub == "show":
        q = flag("--query")
        if "fqdn" in q:
            print("fake-app.example.internal")
        elif "principalId" in q:
            print("00000000-0000-0000-0000-000000000099")
        sys.exit(0)
    if cmd == "keyvault" and sub == "set-policy":
        if os.environ.get("AZ_POLICY_FAIL") == "1":
            sys.stderr.write("set-policy failed\n")
            sys.exit(1)
        sys.exit(0)
    if cmd == "containerapp" and sub == "create" and os.environ.get("AZ_CREATE_EXISTS") == "1":
        sys.stderr.write("app exists\n")
        sys.exit(1)
    sys.exit(0)
    """
).lstrip()


def _flag(args, name):
    if name not in args:
        return None
    i = args.index(name)
    return args[i + 1] if i + 1 < len(args) else None


def _values_after(args, flag):
    if flag not in args:
        return []
    i = args.index(flag) + 1
    out = []
    while i < len(args) and not args[i].startswith("-"):
        out.append(args[i])
        i += 1
    return out


def _cmds(lines, *prefix):
    return [args for args in lines if tuple(args[: len(prefix)]) == prefix]


class DeployUpdateTests(unittest.TestCase):
    def run_deploy(self, stub_dir, extra):
        log = os.path.join(stub_dir, "az.log")
        if os.path.exists(log):
            os.remove(log)
        env = {
            k: v for k, v in os.environ.items()
            if not k.startswith(("AUTH_", "AZ_")) and k != "ACR_NAME"
        }
        env.update(
            PATH=stub_dir + os.pathsep + "/usr/bin:/bin",
            AZ_LOG=log,
            AZ_STATE=os.path.join(stub_dir, "acr-created"),
            AZ_REDACT=SECRET,
            HOME=env.get("HOME", "/tmp"),
        )
        env.update(extra)
        r = subprocess.run(
            ["bash", os.path.join(REPO, "deploy.sh")],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        lines = []
        if os.path.exists(log):
            with open(log) as f:
                lines = [ln.split("\t") for ln in f.read().splitlines() if ln]
        blob = r.stdout + r.stderr + "\n" + "\n".join(" ".join(a) for a in lines)
        self.assertFalse(SECRET in blob, "secret leaked into deploy output or the az log")
        return r, lines

    def test_second_deploy_keeps_env_image_and_registry(self):
        with tempfile.TemporaryDirectory() as d:
            az = os.path.join(d, "az")
            with open(az, "w") as f:
                f.write(AZ_STUB)
            os.chmod(az, os.stat(az).st_mode | stat.S_IEXEC)

            r1, lines1 = self.run_deploy(d, {})
            self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
            creates = _cmds(lines1, "acr", "create")
            self.assertEqual(len(creates), 1)
            acr = _flag(creates[0], "-n")
            self.assertEqual(acr, "acrjarvismcp")
            image = acr + IMAGE_SUFFIX
            app_create = _cmds(lines1, "containerapp", "create")
            self.assertEqual(_flag(app_create[0], "--image"), image)
            plain_update = _cmds(lines1, "containerapp", "update")
            self.assertEqual(len(plain_update), 1)
            self.assertEqual(_flag(plain_update[0], "--image"), image)
            self.assertNotIn("--set-env-vars", plain_update[0])
            policy = _cmds(lines1, "keyvault", "set-policy")
            self.assertEqual(len(policy), 1)
            self.assertEqual(_flag(policy[0], "--name"), VAULT_NAME)
            self.assertNotIn(".", _flag(policy[0], "--name"))
            self.assertNotIn("NOTE:", r1.stdout)

            r2, lines2 = self.run_deploy(
                d,
                {
                    "AUTH_CLIENT_ID": "app-id",
                    "AUTH_TENANT_ID": "tenant-id",
                    "AUTH_CLIENT_SECRET": SECRET,
                    "AZ_CREATE_EXISTS": "1",
                },
            )
            blob2 = r2.stdout + r2.stderr
            self.assertEqual(r2.returncode, 0, blob2)
            self.assertEqual(_cmds(lines2, "acr", "create"), [])
            self.assertEqual(len(_cmds(lines2, "acr", "show")), 1)
            self.assertIn("app exists", blob2)
            update = _cmds(lines2, "containerapp", "update")
            self.assertEqual(len(update), 1)
            args = update[0]
            self.assertEqual(_flag(args, "--image"), image)
            self.assertNotIn("--replace-env-vars", args)
            pairs = _values_after(args, "--set-env-vars")
            got = dict(p.split("=", 1) for p in pairs)
            self.assertEqual(
                got,
                {
                    "JARVIS_TRADING_API": "https://trading.landrycmd.com",
                    "KEY_VAULT_URL": "https://kv-jarvis-lab2.vault.azure.net/",
                    "JARVIS_TOKEN_SECRET_NAME": "jarvis-trading-token",
                    "AUTH_CLIENT_ID": "app-id",
                    "AUTH_TENANT_ID": "tenant-id",
                    "PUBLIC_BASE_URL": "https://fake-app.example.internal",
                    "AUTH_CLIENT_SECRET": "secretref:auth-client-secret",
                },
            )
            self.assertNotIn("--secrets", args)
            secret_set = _cmds(lines2, "containerapp", "secret", "set")
            self.assertEqual(len(secret_set), 1)
            self.assertEqual(_flag(secret_set[0], "--secrets"), "auth-client-secret=***")
            self.assertEqual(_flag(_cmds(lines2, "keyvault", "set-policy")[0], "--name"), VAULT_NAME)

    def test_acr_name_override_is_reused(self):
        with tempfile.TemporaryDirectory() as d:
            az = os.path.join(d, "az")
            with open(az, "w") as f:
                f.write(AZ_STUB)
            os.chmod(az, os.stat(az).st_mode | stat.S_IEXEC)
            r1, lines1 = self.run_deploy(d, {"ACR_NAME": "acrjarviscustom1"})
            self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
            self.assertEqual(_flag(_cmds(lines1, "acr", "create")[0], "-n"), "acrjarviscustom1")
            r2, lines2 = self.run_deploy(d, {"ACR_NAME": "acrjarviscustom1", "AZ_CREATE_EXISTS": "1"})
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            self.assertEqual(_cmds(lines2, "acr", "create"), [])
            image = "acrjarviscustom1" + IMAGE_SUFFIX
            self.assertEqual(_flag(_cmds(lines2, "containerapp", "update")[0], "--image"), image)

    def test_vault_grant_failure_stops_the_script(self):
        with tempfile.TemporaryDirectory() as d:
            az = os.path.join(d, "az")
            with open(az, "w") as f:
                f.write(AZ_STUB)
            os.chmod(az, os.stat(az).st_mode | stat.S_IEXEC)
            r, lines = self.run_deploy(d, {"AZ_POLICY_FAIL": "1"})
            self.assertNotEqual(r.returncode, 0)
            self.assertNotIn("NOTE:", r.stdout)
            self.assertIn("set-policy failed", r.stderr)
            self.assertEqual(_cmds(lines, "containerapp", "update"), [])
            self.assertEqual(_flag(_cmds(lines, "keyvault", "set-policy")[0], "--name"), VAULT_NAME)


if __name__ == "__main__":
    unittest.main()
