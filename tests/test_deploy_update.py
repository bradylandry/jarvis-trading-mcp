"""deploy.sh keeps env, image, registry pull, and the Key Vault grant. az is a stub on PATH."""
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET = "fake-client-secret-value-0123"
VAULT_NAME = "kv-jarvis-lab2"
AUTH_KV_SECRET = "jarvis-trading-auth-client-secret"
APP = "jarvis-trading-mcp"
REV_NAME = "jarvis-trading-mcp--deploy"
DEFAULT_SUB = "Azure subscription 1 - gmail"
VAULT_ID = (
    "/subscriptions/fake/resourceGroups/rg-other/providers/Microsoft.KeyVault/vaults/"
    + VAULT_NAME
)
PID = "00000000-0000-0000-0000-000000000099"
BACKEND_ENV = {
    "JARVIS_TRADING_API": "https://trading.landrycmd.com",
    "KEY_VAULT_URL": "https://kv-jarvis-lab2.vault.azure.net/",
    "JARVIS_TOKEN_SECRET_NAME": "jarvis-trading-token",
}

AZ_STUB = textwrap.dedent(
    r"""
    #!/usr/bin/env python3
    import os, sys
    log = os.environ["AZ_LOG"]
    state = os.environ["AZ_STATE"]
    redact = os.environ.get("AZ_REDACT", "")
    args = sys.argv[1:]
    safe = []
    leaked = False
    for a in args:
        if redact and redact in a:
            leaked = True
            a = a.replace(redact, "***")
        safe.append(a)
    if leaked:
        # The raw value stays out of the log. The marker is how the test sees it.
        safe.append("SECRET_IN_ARGV")
    if os.environ.get("AUTH_CLIENT_SECRET"):
        safe.append("SECRET_IN_ENV")
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
        if os.environ.get("AZ_ACR_SHOW_FAIL") == "1":
            # Exit 1 even though the text names ResourceNotFound. Existence is the exit code.
            sys.stderr.write("ERROR: (ResourceNotFound) registry control plane unavailable\n")
            sys.exit(1)
        name = flag("-n") or flag("--name")
        if name not in created():
            sys.stderr.write("ERROR: (Missing) registry lookup returned no record.\n")
            sys.exit(3)
        if flag("--query") == "id":
            rg = flag("-g") or flag("--resource-group") or "rg"
            print(
                "/subscriptions/fake/resourceGroups/"
                + rg
                + "/providers/Microsoft.ContainerRegistry/registries/"
                + name
            )
        sys.exit(0)
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
        if os.environ.get("AZ_APP_SHOW_FAIL") == "1":
            # Exit 1. The words below must not be treated as "app exists" or "not found".
            sys.stderr.write(
                "ERROR: (ResourceNotFound) control plane unavailable; already exists is not this error\n"
            )
            sys.exit(1)
        q = flag("--query")
        if not q:
            if os.environ.get("AZ_CREATE_EXISTS") == "1":
                sys.exit(0)
            sys.stderr.write("ERROR: (Missing) container app lookup returned no record.\n")
            sys.exit(3)
        if "fqdn" in q:
            print("fake-app.example.internal")
        elif "principalId" in q:
            counter = os.path.join(os.path.dirname(state), "pid-shows")
            n = 0
            if os.path.exists(counter):
                n = int(open(counter).read() or "0")
            n += 1
            with open(counter, "w") as f:
                f.write(str(n))
            blank = int(os.environ.get("AZ_PID_BLANK_COUNT", "0") or "0")
            if n <= blank:
                print("")
            else:
                print("00000000-0000-0000-0000-000000000099")
        sys.exit(0)
    if cmd == "keyvault" and sub == "show":
        q = flag("--query") or ""
        if "enableRbacAuthorization" in q:
            print("true" if os.environ.get("AZ_KV_RBAC") == "1" else "false")
        elif q == "id":
            print(
                "/subscriptions/fake/resourceGroups/rg-other/providers/"
                "Microsoft.KeyVault/vaults/kv-jarvis-lab2"
            )
        sys.exit(0)
    if cmd == "keyvault" and sub == "set-policy":
        if os.environ.get("AZ_POLICY_FAIL") == "1":
            sys.stderr.write("set-policy failed\n")
            sys.exit(1)
        sys.exit(0)
    if cmd == "keyvault" and sub == "secret" and len(args) > 2 and args[2] == "set":
        path = flag("--file")
        marker = ""
        if path and redact and os.path.isfile(path):
            data = open(path, "rb").read()
            raw = redact.encode()
            if data == raw:
                marker = "SECRET_FILE_EXACT"
            elif raw in data:
                marker = "SECRET_FILE_HAS_VALUE_PLUS_EXTRA"
        if marker:
            with open(log, "a") as f:
                f.write(marker + "\n")
        sys.exit(0)
    if cmd == "role" and sub == "assignment" and len(args) > 2 and args[2] == "create":
        if os.environ.get("AZ_ROLE_FAIL") == "1":
            sys.stderr.write("ERROR: (AuthorizationFailed) no permission to assign role\n")
            sys.exit(1)
        if os.environ.get("AZ_ROLE_EXISTS") == "1":
            sys.stderr.write(
                "ERROR: (RoleAssignmentExists) The role assignment already exists.\n"
            )
            sys.exit(1)
        sys.exit(0)
    if cmd == "containerapp" and sub == "create" and os.environ.get("AZ_CREATE_EXISTS") == "1":
        sys.stderr.write(
            "ERROR: (ContainerAppAlreadyExists) The container app "
            "'jarvis-trading-mcp' already exists.\n"
        )
        sys.exit(1)
    if cmd == "containerapp" and sub == "create" and os.environ.get("AZ_CREATE_FAIL") == "1":
        sys.stderr.write("ERROR: (InvalidResource) location is unavailable\n")
        sys.exit(1)
    if cmd == "containerapp" and sub == "update":
        q = flag("--query") or ""
        if "latestRevisionName" in q:
            print("jarvis-trading-mcp--deploy")
        sys.exit(0)
    if cmd == "containerapp" and sub == "revision" and len(args) > 2 and args[2] == "show":
        if "runningState" in (flag("--query") or ""):
            forced = os.environ.get("AZ_REVISION_STATE", "")
            if forced:
                print(forced)
                sys.exit(0)
            counter = os.path.join(os.path.dirname(state), "rev-shows")
            n = 0
            if os.path.exists(counter):
                n = int(open(counter).read() or "0")
            n += 1
            with open(counter, "w") as f:
                f.write(str(n))
            pending = int(os.environ.get("AZ_REVISION_PENDING", "0") or "0")
            print("Processing" if n <= pending else "Running")
        sys.exit(0)
    if cmd == "containerapp" and sub == "secret" and len(args) > 2 and args[2] == "list":
        if os.environ.get("AZ_NO_REG_SECRET") == "1":
            sys.exit(0)
        acr = os.environ.get("ACR_NAME") or "acrjarvismcp"
        print(acr + "azurecrio-" + acr)
        sys.exit(0)
    if cmd == "containerapp" and sub == "secret" and len(args) > 2 and args[2] == "remove":
        sys.exit(0)
    if cmd == "containerapp" and sub == "secret" and len(args) > 2 and args[2] == "set":
        counter = os.path.join(os.path.dirname(state), "secret-set-tries")
        n = 0
        if os.path.exists(counter):
            n = int(open(counter).read() or "0")
        n += 1
        with open(counter, "w") as f:
            f.write(str(n))
        fail_n = int(os.environ.get("AZ_SECRET_SET_FAILS", "0") or "0")
        if n <= fail_n:
            sys.stderr.write("ERROR: (SecretRefNotResolved) keyvaultref not readable yet\n")
            sys.exit(1)
        sys.exit(0)
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


def _all_flags(args, name):
    out = []
    for i, arg in enumerate(args):
        if arg == name and i + 1 < len(args):
            out.append(args[i + 1])
    return out


def _cmds(lines, *prefix):
    return [args for args in lines if tuple(args[: len(prefix)]) == prefix]


class DeployUpdateTests(unittest.TestCase):
    def run_deploy(self, stub_dir, extra):
        log = os.path.join(stub_dir, "az.log")
        if os.path.exists(log):
            os.remove(log)
        for name in ("rev-shows", "secret-set-tries"):
            path = os.path.join(stub_dir, name)
            if os.path.exists(path):
                os.remove(path)
        env = {
            k: v for k, v in os.environ.items()
            if not k.startswith(("AUTH_", "AZ_")) and k not in ("ACR_NAME", "KV_SUBSCRIPTION")
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
        self.assertNotIn("SECRET_IN_ARGV", blob, "client secret was an az argument")
        self.assertNotIn("SECRET_IN_ENV", blob, "client secret was exported to az")
        self.assertNotIn(SECRET, blob, "secret leaked into deploy output or the az log")
        self.assertNotIn("SECRET_FILE_HAS_VALUE_PLUS_EXTRA", blob)
        return r, lines

    def install_az(self, stub_dir):
        az = os.path.join(stub_dir, "az")
        with open(az, "w") as f:
            f.write(AZ_STUB)
        os.chmod(az, os.stat(az).st_mode | stat.S_IEXEC)

    def assertRegistryPull(self, lines, image):
        server = image.split("/")[0]
        reg = _cmds(lines, "containerapp", "registry", "set")
        self.assertEqual(len(reg), 1, lines)
        self.assertEqual(_flag(reg[0], "--server"), server)
        self.assertEqual(_flag(reg[0], "--identity"), "system")
        self.assertNotIn("--password", reg[0])
        self.assertNotIn("--username", reg[0])
        update = _cmds(lines, "containerapp", "update")
        self.assertEqual(len(update), 1)
        self.assertEqual(_flag(update[0], "--image"), image)
        self.assertLess(lines.index(reg[0]), lines.index(update[0]))
        pulls = [
            a for a in _cmds(lines, "role", "assignment", "create")
            if _flag(a, "--role") == "AcrPull"
        ]
        self.assertEqual(len(pulls), 1, lines)
        self.assertEqual(_flag(pulls[0], "--assignee-object-id"), PID)
        self.assertEqual(_flag(pulls[0], "--assignee-principal-type"), "ServicePrincipal")
        self.assertEqual(
            _flag(pulls[0], "--scope"),
            "/subscriptions/fake/resourceGroups/rg-jarvis-mcp/providers/"
            "Microsoft.ContainerRegistry/registries/" + server.split(".")[0],
        )
        self.assertLess(lines.index(pulls[0]), lines.index(reg[0]))
        for args in lines:
            self.assertNotIn("--registry-password", args)
            self.assertNotIn("--password", args)

    def assert_unique_image(self, lines, acr):
        update = _cmds(lines, "containerapp", "update")
        self.assertEqual(len(update), 1, lines)
        image = _flag(update[0], "--image")
        prefix = acr + ".azurecr.io/" + APP + ":"
        self.assertTrue(image.startswith(prefix), image)
        tag = image[len(prefix):]
        self.assertRegex(tag, r"^[0-9]{23}$")
        builds = _cmds(lines, "acr", "build")
        self.assertEqual(len(builds), 1, lines)
        self.assertEqual(_flag(builds[0], "-r"), acr)
        self.assertEqual(_all_flags(builds[0], "-t"), [APP + ":" + tag, APP + ":latest"])
        return image

    def assert_rollout_healthy(self, lines, acr):
        updates = _cmds(lines, "containerapp", "update")
        self.assertEqual(_flag(updates[0], "--query"), "properties.latestRevisionName")
        self.assertEqual(_flag(updates[0], "-o"), "tsv")
        revs = _cmds(lines, "containerapp", "revision", "show")
        self.assertGreaterEqual(len(revs), 1, lines)
        self.assertEqual(_flag(revs[-1], "--query"), "properties.runningState")
        self.assertEqual(_flag(revs[-1], "--revision"), REV_NAME)
        self.assertLess(lines.index(updates[0]), lines.index(revs[0]))
        acr_up = _cmds(lines, "acr", "update")
        self.assertEqual(len(acr_up), 1, lines)
        self.assertEqual(_flag(acr_up[0], "-n"), acr)
        self.assertEqual(_flag(acr_up[0], "--admin-enabled"), "false")
        self.assertEqual(_flag(acr_up[0], "-o"), "none")
        self.assertLess(lines.index(revs[-1]), lines.index(acr_up[0]))
        self.assertEqual(len(_cmds(lines, "containerapp", "secret", "list")), 1, lines)
        removes = _cmds(lines, "containerapp", "secret", "remove")
        self.assertEqual(len(removes), 1, lines)
        self.assertEqual(_flag(removes[0], "--secret-names"), acr + "azurecrio-" + acr)
        self.assertLess(lines.index(acr_up[0]), lines.index(removes[0]))
        for args in lines:
            joined = " ".join(args)
            self.assertNotIn("properties.provisioningState", joined)

    def test_second_deploy_keeps_env_image_and_registry(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)

            r1, lines1 = self.run_deploy(d, {})
            self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
            creates = _cmds(lines1, "acr", "create")
            self.assertEqual(len(creates), 1)
            acr = _flag(creates[0], "-n")
            self.assertEqual(acr, "acrjarvismcp")
            self.assertEqual(_flag(creates[0], "--admin-enabled"), "true")
            image = self.assert_unique_image(lines1, acr)
            app_create = _cmds(lines1, "containerapp", "create")
            self.assertEqual(_flag(app_create[0], "--image"), image)
            self.assertEqual(_flag(app_create[0], "--registry-server"), acr + ".azurecr.io")
            self.assertNotIn("--registry-identity", app_create[0])
            plain_update = _cmds(lines1, "containerapp", "update")
            self.assertEqual(len(plain_update), 1)
            self.assertEqual(_flag(plain_update[0], "--image"), image)
            self.assertNotIn("--replace-env-vars", plain_update[0])
            self.assertEqual(
                dict(p.split("=", 1) for p in _values_after(plain_update[0], "--set-env-vars")),
                BACKEND_ENV,
            )
            self.assertEqual(_cmds(lines1, "keyvault", "secret", "set"), [])
            self.assertEqual(_cmds(lines1, "containerapp", "secret", "set"), [])
            self.assertRegistryPull(lines1, image)
            policy = _cmds(lines1, "keyvault", "set-policy")
            self.assertEqual(len(policy), 1)
            self.assertEqual(_flag(policy[0], "--name"), VAULT_NAME)
            self.assertNotIn(".", _flag(policy[0], "--name"))
            self.assertEqual(_flag(policy[0], "--subscription"), DEFAULT_SUB)
            self.assertEqual(_flag(policy[0], "-o"), "none")
            for args in _cmds(lines1, "keyvault", "show"):
                self.assertEqual(_flag(args, "--subscription"), DEFAULT_SUB)
            self.assertNotIn("NOTE:", r1.stdout)
            self.assertIn("NEXT:", r1.stdout)
            self.assert_rollout_healthy(lines1, acr)

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
            self.assertEqual(_cmds(lines2, "containerapp", "create"), [])
            # existence check, then the id used as the AcrPull scope
            self.assertEqual(len(_cmds(lines2, "acr", "show")), 2)
            self.assertIn("app exists", blob2)
            image2 = self.assert_unique_image(lines2, acr)
            self.assertNotEqual(image, image2)
            update = _cmds(lines2, "containerapp", "update")
            self.assertEqual(len(update), 1)
            args = update[0]
            self.assertEqual(_flag(args, "--image"), image2)
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
            self.assertEqual(
                _flag(secret_set[0], "--secrets"),
                "auth-client-secret=keyvaultref:https://kv-jarvis-lab2.vault.azure.net/secrets/"
                + AUTH_KV_SECRET
                + ",identityref:system",
            )
            kv_set = _cmds(lines2, "keyvault", "secret", "set")
            self.assertEqual(len(kv_set), 1)
            self.assertEqual(_flag(kv_set[0], "--vault-name"), VAULT_NAME)
            self.assertEqual(_flag(kv_set[0], "--name"), AUTH_KV_SECRET)
            self.assertTrue(_flag(kv_set[0], "--file"))
            self.assertNotIn("--value", kv_set[0])
            self.assertIn(["SECRET_FILE_EXACT"], lines2)
            policy2 = _cmds(lines2, "keyvault", "set-policy")
            self.assertEqual(_flag(policy2[0], "--name"), VAULT_NAME)
            self.assertEqual(_flag(policy2[0], "--subscription"), DEFAULT_SUB)
            self.assertEqual(_flag(policy2[0], "-o"), "none")
            for args in _cmds(lines2, "keyvault", "show") + _cmds(lines2, "keyvault", "secret", "set"):
                self.assertEqual(_flag(args, "--subscription"), DEFAULT_SUB)
            self.assertEqual(
                [
                    _flag(a, "--role")
                    for a in _cmds(lines2, "role", "assignment", "create")
                    if _flag(a, "--role") == "Key Vault Secrets User"
                ],
                [],
            )
            self.assertRegistryPull(lines2, image2)
            self.assert_rollout_healthy(lines2, acr)
            self.assertIn("auth enabled", blob2)

    def test_acr_name_override_is_reused(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r1, lines1 = self.run_deploy(d, {"ACR_NAME": "acrjarviscustom1"})
            self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
            self.assertEqual(_flag(_cmds(lines1, "acr", "create")[0], "-n"), "acrjarviscustom1")
            r2, lines2 = self.run_deploy(d, {"ACR_NAME": "acrjarviscustom1", "AZ_CREATE_EXISTS": "1"})
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            self.assertEqual(_cmds(lines2, "acr", "create"), [])
            self.assertEqual(_cmds(lines2, "containerapp", "create"), [])
            image1 = self.assert_unique_image(lines1, "acrjarviscustom1")
            image2 = self.assert_unique_image(lines2, "acrjarviscustom1")
            self.assertNotEqual(image1, image2)
            self.assertRegistryPull(lines2, image2)
            self.assert_rollout_healthy(lines2, "acrjarviscustom1")

    def test_no_auth_rerun_sets_backend_env(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(d, {"AZ_CREATE_EXISTS": "1"})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("app exists", r.stdout)
            update = _cmds(lines, "containerapp", "update")
            self.assertEqual(len(update), 1)
            self.assertNotIn("--replace-env-vars", update[0])
            pairs = _values_after(update[0], "--set-env-vars")
            got = dict(p.split("=", 1) for p in pairs)
            self.assertEqual(got, BACKEND_ENV)
            for key in got:
                self.assertFalse(key.startswith("AUTH_"))
            image = self.assert_unique_image(lines, "acrjarvismcp")
            self.assertRegistryPull(lines, image)
            self.assert_rollout_healthy(lines, "acrjarvismcp")

    def test_create_failure_other_than_exists_stops(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(d, {"AZ_CREATE_FAIL": "1"})
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("InvalidResource", r.stderr)
            self.assertNotIn("app exists", r.stdout + r.stderr)
            shows = _cmds(lines, "containerapp", "show")
            self.assertEqual(len(shows), 1)
            self.assertIsNone(_flag(shows[0], "--query"))
            self.assertEqual(len(_cmds(lines, "containerapp", "create")), 1)
            self.assertEqual(_cmds(lines, "containerapp", "registry", "set"), [])
            self.assertEqual(_cmds(lines, "containerapp", "update"), [])
            self.assertEqual(_cmds(lines, "keyvault", "set-policy"), [])
            self.assertEqual(_cmds(lines, "role", "assignment", "create"), [])

    def test_rbac_vault_assigns_secret_scoped_role(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(
                d,
                {
                    "AZ_KV_RBAC": "1",
                    "AZ_CREATE_EXISTS": "1",
                    "AUTH_CLIENT_ID": "app-id",
                    "AUTH_TENANT_ID": "tenant-id",
                    "AUTH_CLIENT_SECRET": SECRET,
                },
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(_cmds(lines, "keyvault", "set-policy"), [])
            shows = _cmds(lines, "keyvault", "show")
            self.assertTrue(
                any("enableRbacAuthorization" in (_flag(a, "--query") or "") for a in shows)
            )
            self.assertEqual(_flag(shows[0], "-n"), VAULT_NAME)
            for args in shows + _cmds(lines, "keyvault", "secret", "set"):
                self.assertEqual(_flag(args, "--subscription"), DEFAULT_SUB)
            roles = _cmds(lines, "role", "assignment", "create")
            kv_scopes = [
                _flag(a, "--scope") for a in roles if _flag(a, "--role") == "Key Vault Secrets User"
            ]
            self.assertEqual(
                kv_scopes,
                [
                    VAULT_ID + "/secrets/jarvis-trading-token",
                    VAULT_ID + "/secrets/" + AUTH_KV_SECRET,
                ],
            )
            joined = "\n".join(" ".join(a) for a in lines)
            self.assertIn("SECRET_FILE_EXACT", joined)
            image = self.assert_unique_image(lines, "acrjarvismcp")
            self.assertRegistryPull(lines, image)
            self.assert_rollout_healthy(lines, "acrjarvismcp")

    def test_existing_role_assignment_does_not_stop_deploy(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(
                d, {"AZ_KV_RBAC": "1", "AZ_ROLE_EXISTS": "1", "AZ_CREATE_EXISTS": "1"}
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertGreaterEqual(len(_cmds(lines, "role", "assignment", "create")), 1)
            self.assertEqual(_cmds(lines, "keyvault", "set-policy"), [])
            self.assertEqual(len(_cmds(lines, "containerapp", "update")), 1)
            self.assertEqual(len(_cmds(lines, "containerapp", "registry", "set")), 1)

    def test_other_grant_error_stops_before_update(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(d, {"AZ_KV_RBAC": "1", "AZ_ROLE_FAIL": "1"})
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("AuthorizationFailed", r.stderr)
            self.assertEqual(_cmds(lines, "keyvault", "set-policy"), [])
            self.assertEqual(_cmds(lines, "containerapp", "registry", "set"), [])
            self.assertEqual(_cmds(lines, "containerapp", "update"), [])

    def test_acr_pull_error_stops_before_image_update(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(d, {"AZ_ROLE_FAIL": "1"})
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("AuthorizationFailed", r.stderr)
            self.assertEqual(len(_cmds(lines, "keyvault", "set-policy")), 1)
            self.assertEqual(_cmds(lines, "containerapp", "registry", "set"), [])
            self.assertEqual(_cmds(lines, "containerapp", "update"), [])

    def test_empty_principal_stops_before_grant(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(d, {"AZ_PID_BLANK_COUNT": "9"})
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("principalId", r.stderr)
            self.assertEqual(_cmds(lines, "keyvault", "set-policy"), [])
            self.assertEqual(_cmds(lines, "role", "assignment", "create"), [])
            self.assertEqual(_cmds(lines, "containerapp", "registry", "set"), [])
            self.assertEqual(_cmds(lines, "containerapp", "update"), [])

    def test_principal_blank_then_present_is_used(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(d, {"AZ_PID_BLANK_COUNT": "1"})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            pid_shows = [
                a for a in _cmds(lines, "containerapp", "show")
                if "principalId" in (_flag(a, "--query") or "")
            ]
            self.assertGreaterEqual(len(pid_shows), 2)
            policy = _cmds(lines, "keyvault", "set-policy")
            self.assertEqual(_flag(policy[0], "--object-id"), PID)

    def test_vault_grant_failure_stops_the_script(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(d, {"AZ_POLICY_FAIL": "1"})
            self.assertNotEqual(r.returncode, 0)
            self.assertNotIn("NOTE:", r.stdout)
            self.assertIn("set-policy failed", r.stderr)
            self.assertEqual(_cmds(lines, "containerapp", "update"), [])
            policy = _cmds(lines, "keyvault", "set-policy")
            self.assertEqual(_flag(policy[0], "--name"), VAULT_NAME)
            self.assertEqual(_flag(policy[0], "-o"), "none")
            self.assertEqual(_flag(policy[0], "--subscription"), DEFAULT_SUB)

    def test_unhealthy_revision_stops_before_admin_disable(self):
        for state in ("Failed", "Degraded", "ActivationFailed"):
            with tempfile.TemporaryDirectory() as d:
                self.install_az(d)
                r, lines = self.run_deploy(d, {"AZ_REVISION_STATE": state})
                self.assertNotEqual(r.returncode, 0, state)
                self.assertIn("revision " + REV_NAME + " is " + state, r.stderr)
                self.assertNotIn("NEXT:", r.stdout)
                self.assertNotIn("auth enabled", r.stdout)
                self.assertGreaterEqual(len(_cmds(lines, "containerapp", "revision", "show")), 1)
                self.assertEqual(_cmds(lines, "acr", "update"), [])
                self.assertEqual(_cmds(lines, "containerapp", "secret", "remove"), [])

    def test_revision_polls_past_nonterminal_state(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(d, {"AZ_REVISION_PENDING": "1"})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(len(_cmds(lines, "containerapp", "revision", "show")), 2)
            self.assertIn("NEXT:", r.stdout)
            self.assert_rollout_healthy(lines, "acrjarvismcp")

    def test_app_show_error_stops_before_create(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(d, {"AZ_APP_SHOW_FAIL": "1"})
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("control plane unavailable", r.stderr)
            self.assertNotIn("app exists", r.stdout + r.stderr)
            self.assertEqual(_cmds(lines, "containerapp", "create"), [])
            self.assertEqual(_cmds(lines, "containerapp", "update"), [])
            self.assertEqual(_cmds(lines, "containerapp", "registry", "set"), [])

    def test_acr_show_error_stops_before_create(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(d, {"AZ_ACR_SHOW_FAIL": "1"})
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("registry control plane unavailable", r.stderr)
            self.assertEqual(_cmds(lines, "acr", "create"), [])
            self.assertEqual(_cmds(lines, "containerapp", "create"), [])
            self.assertEqual(_cmds(lines, "containerapp", "update"), [])

    def test_keyvault_subscription_override(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(
                d,
                {
                    "KV_SUBSCRIPTION": "lab-subscription",
                    "AZ_CREATE_EXISTS": "1",
                    "AUTH_CLIENT_ID": "app-id",
                    "AUTH_TENANT_ID": "tenant-id",
                    "AUTH_CLIENT_SECRET": SECRET,
                },
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            kv = (
                _cmds(lines, "keyvault", "show")
                + _cmds(lines, "keyvault", "set-policy")
                + _cmds(lines, "keyvault", "secret", "set")
            )
            self.assertGreaterEqual(len(_cmds(lines, "keyvault", "show")), 1)
            self.assertEqual(len(_cmds(lines, "keyvault", "set-policy")), 1)
            self.assertEqual(len(_cmds(lines, "keyvault", "secret", "set")), 1)
            for args in kv:
                self.assertEqual(_flag(args, "--subscription"), "lab-subscription")

    def test_rbac_secret_set_retries_then_updates(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(
                d,
                {
                    "AZ_KV_RBAC": "1",
                    "AZ_SECRET_SET_FAILS": "2",
                    "AZ_CREATE_EXISTS": "1",
                    "AUTH_CLIENT_ID": "app-id",
                    "AUTH_TENANT_ID": "tenant-id",
                    "AUTH_CLIENT_SECRET": SECRET,
                },
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            secret_sets = _cmds(lines, "containerapp", "secret", "set")
            self.assertEqual(len(secret_sets), 3)
            auth_grants = [
                a for a in _cmds(lines, "role", "assignment", "create")
                if _flag(a, "--role") == "Key Vault Secrets User"
                and (_flag(a, "--scope") or "").endswith("/secrets/" + AUTH_KV_SECRET)
            ]
            self.assertEqual(len(auth_grants), 1)
            self.assertLess(lines.index(auth_grants[0]), lines.index(secret_sets[0]))
            self.assertEqual(len(_cmds(lines, "containerapp", "update")), 1)

    def test_rbac_secret_set_stops_after_retries(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(
                d,
                {
                    "AZ_KV_RBAC": "1",
                    "AZ_SECRET_SET_FAILS": "9",
                    "AZ_CREATE_EXISTS": "1",
                    "AUTH_CLIENT_ID": "app-id",
                    "AUTH_TENANT_ID": "tenant-id",
                    "AUTH_CLIENT_SECRET": SECRET,
                },
            )
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(len(_cmds(lines, "containerapp", "secret", "set")), 5)
            self.assertEqual(_cmds(lines, "containerapp", "registry", "set"), [])
            self.assertEqual(_cmds(lines, "containerapp", "update"), [])
            self.assertIn("after retries", r.stderr)
            self.assertIn("Re-run", r.stderr)

    def test_access_policy_secret_set_does_not_retry(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(
                d,
                {
                    "AZ_SECRET_SET_FAILS": "2",
                    "AZ_CREATE_EXISTS": "1",
                    "AUTH_CLIENT_ID": "app-id",
                    "AUTH_TENANT_ID": "tenant-id",
                    "AUTH_CLIENT_SECRET": SECRET,
                },
            )
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(len(_cmds(lines, "containerapp", "secret", "set")), 1)
            self.assertEqual(_cmds(lines, "containerapp", "update"), [])
            self.assertIn("containerapp secret set failed", r.stderr)
            self.assertNotIn("after retries", r.stderr)

    def test_missing_registry_password_secret_is_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            self.install_az(d)
            r, lines = self.run_deploy(d, {"AZ_NO_REG_SECRET": "1"})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(len(_cmds(lines, "containerapp", "secret", "list")), 1)
            self.assertEqual(_cmds(lines, "containerapp", "secret", "remove"), [])
            self.assertEqual(_flag(_cmds(lines, "acr", "update")[0], "--admin-enabled"), "false")

    def test_readme_notes_one_off_registry_cleanup(self):
        with open(os.path.join(REPO, "README.md")) as f:
            readme = f.read()
        with open(os.path.join(REPO, "deploy.sh")) as f:
            script = f.read()
        self.assertIn("az containerapp registry remove", readme)
        self.assertIn("az acr delete", readme)
        self.assertNotIn("acr delete", script)
        self.assertNotIn("registry remove", script)


if __name__ == "__main__":
    unittest.main()
