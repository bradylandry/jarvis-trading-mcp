"""Backend token rotation: a 401 rereads the token source once and retries once."""
import os
import threading
import unittest

import httpx

from tests import _fakes

_real_get = httpx.get


class TokenRefreshTests(unittest.TestCase):
    def setUp(self):
        self.saved_env = dict(os.environ)
        self.w = _fakes.World()
        self.srv = _fakes.install(self.w)

    def tearDown(self):
        httpx.get = _real_get
        os.environ.clear()
        os.environ.update(self.saved_env)

    def rotate(self):
        self.w.vault = self.w.accepted = "tok-two-bbbbbbbb"

    def test_rotation_recovers_without_restart(self):
        self.assertEqual(self.srv.get_crash_risk(), {"composite": 4.2})
        self.rotate()
        self.assertEqual(self.srv.get_crash_risk(), {"composite": 4.2})
        self.assertEqual(self.w.vault_reads, 2)
        self.assertEqual(self.w.sent, ["tok-one-aaaaaaaa", "tok-one-aaaaaaaa", "tok-two-bbbbbbbb"])
        # later calls use the new token straight away
        self.srv.get_crash_risk()
        self.assertEqual(self.w.vault_reads, 2)
        self.assertEqual(self.w.sent[-1], "tok-two-bbbbbbbb")

    def test_still_401_after_reread_gives_existing_error_once(self):
        self.srv.get_crash_risk()
        self.w.vault = "tok-two-bbbbbbbb"
        self.w.accepted = "tok-three-cccccccc"  # vault not updated to the accepted token
        with self.assertRaises(RuntimeError) as cm:
            self.srv.get_crash_risk()
        self.assertEqual(
            str(cm.exception),
            "trading API rejected the token (401). Confirm the token is still active.",
        )
        self.assertEqual(self.w.vault_reads, 2)
        self.assertEqual(self.w.sent, ["tok-one-aaaaaaaa", "tok-one-aaaaaaaa", "tok-two-bbbbbbbb"])

    def test_unchanged_token_after_reread_is_not_resent(self):
        self.srv.get_crash_risk()
        self.w.accepted = "tok-revoked-zzzz"  # token revoked, vault still has the old one
        with self.assertRaises(RuntimeError) as cm:
            self.srv.get_crash_risk()
        self.assertIn("(401)", str(cm.exception))
        self.assertEqual(self.w.vault_reads, 2)
        self.assertEqual(len(self.w.sent), 2)

    def test_non_401_does_not_reread(self):
        self.srv.get_crash_risk()
        self.w.status_override = 500
        with self.assertRaises(RuntimeError) as cm:
            self.srv.get_crash_risk()
        self.assertEqual(str(cm.exception), "trading API returned status 500.")
        self.assertEqual(self.w.vault_reads, 1)
        self.assertEqual(len(self.w.sent), 2)

    def test_vault_failure_on_reread_is_not_cached(self):
        self.srv.get_crash_risk()
        self.rotate()
        self.w.vault_up = False
        with self.assertRaises(RuntimeError):
            self.srv.get_crash_risk()
        self.w.vault_up = True
        self.assertEqual(self.srv.get_crash_risk(), {"composite": 4.2})
        self.assertEqual(self.w.sent[-1], "tok-two-bbbbbbbb")

    def test_tokens_never_in_error_messages(self):
        self.srv.get_crash_risk()
        self.w.accepted = "tok-nobody-has-it"
        try:
            self.srv.get_crash_risk()
        except RuntimeError as e:
            for t in ("tok-one-aaaaaaaa", "tok-nobody-has-it"):
                self.assertNotIn(t, str(e))

    def test_retry_counts_against_rate_cap(self):
        os.environ["JARVIS_TRADING_MAX_CALLS_PER_MIN"] = "2"
        self.srv = _fakes.install(self.w, {"JARVIS_TRADING_MAX_CALLS_PER_MIN": "2"})
        self.srv.get_crash_risk()
        self.rotate()
        # the second call needs 2 upstream requests but only 1 slot is left
        with self.assertRaises(RuntimeError) as cm:
            self.srv.get_crash_risk()
        self.assertIn("rate limit", str(cm.exception))
        self.assertEqual(len(self.w.sent), 2)

    def test_concurrent_401s_reread_vault_once(self):
        self.srv.get_crash_risk()
        self.rotate()
        errors = []

        def call():
            try:
                self.srv.get_crash_risk()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        ts = [threading.Thread(target=call) for _ in range(20)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.w.vault_reads, 2)


if __name__ == "__main__":
    unittest.main()
