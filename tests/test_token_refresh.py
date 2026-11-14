"""Backend token rotation: a 401 rereads the token source once and retries once."""
import os
import threading
import unittest

from tests import _fakes


class TokenRefreshTests(unittest.TestCase):
    def setUp(self):
        self.saved = _fakes.snapshot()
        self.w = _fakes.World()
        self.srv = _fakes.install(self.w)

    def tearDown(self):
        _fakes.restore(self.saved)

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
        with self.assertRaises(RuntimeError) as cm:
            self.srv.get_crash_risk()
        for t in ("tok-one-aaaaaaaa", "tok-nobody-has-it"):
            self.assertNotIn(t, str(cm.exception))

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

    def _burst(self, n=20):
        """Hold every first request until all n have been sent, so the 401s overlap."""
        barrier = threading.Barrier(n)
        inner = threading.local()
        real = _fakes.httpx.get

        def gated(url, params=None, headers=None, timeout=None):
            resp = real(url, params=params, headers=headers, timeout=timeout)
            if not getattr(inner, "seen", False):
                inner.seen = True
                barrier.wait(timeout=10)
            return resp

        _fakes.httpx.get = gated
        errors = []

        def call():
            try:
                self.srv.get_crash_risk()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        ts = [threading.Thread(target=call) for _ in range(n)]
        try:
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            return errors
        finally:
            _fakes.httpx.get = real

    def test_concurrent_401s_after_rotation_reread_vault_once(self):
        self.srv.get_crash_risk()
        self.rotate()
        errors = self._burst()
        self.assertEqual(errors, [])
        self.assertEqual(self.w.vault_reads, 2)

    def test_concurrent_401s_with_revoked_token_reread_vault_once(self):
        self.srv.get_crash_risk()
        self.w.accepted = "tok-revoked-zzzz"  # vault still has the old token
        errors = self._burst()
        self.assertEqual(len(errors), 20)
        self.assertTrue(all("(401)" in str(e) for e in errors))
        self.assertEqual(self.w.vault_reads, 2)
        self.assertEqual(len(self.w.sent), 21)  # no retries with the unchanged token

    def test_concurrent_401s_share_one_failed_vault_reread(self):
        self.srv.get_crash_risk()
        self.rotate()
        self.w.vault_up = False
        errors = self._burst()
        self.assertEqual(len(errors), 20)
        self.assertTrue(all(isinstance(e, RuntimeError) for e in errors))
        self.assertTrue(all("vault unreachable" in str(e) for e in errors))
        for e in errors:
            self.assertNotIn("tok-one-aaaaaaaa", str(e))
            self.assertNotIn("tok-two-bbbbbbbb", str(e))
        # prime read plus one failed reread, shared by the rest of the burst
        self.assertEqual(self.w.vault_reads, 2)
        self.assertIsNone(self.srv._token_cache)
        # the failure is not a cached token: the next call reads the vault again
        with self.assertRaises(RuntimeError):
            self.srv.get_crash_risk()
        self.assertEqual(self.w.vault_reads, 3)
        self.assertIsNone(self.srv._token_cache)
        self.w.vault_up = True
        self.assertEqual(self.srv.get_crash_risk(), {"composite": 4.2})
        self.assertEqual(self.w.vault_reads, 4)
        self.assertEqual(self.w.sent[-1], "tok-two-bbbbbbbb")


if __name__ == "__main__":
    unittest.main()
