"""Tests for the HOTP/TOTP primitives against RFC 4226 test vectors."""

from odoo.tests import TransactionCase, tagged

from odoo.addons.auth_totp.models.totp import TOTP, hotp

RFC4226_SECRET = b"12345678901234567890"
# RFC 4226, Appendix D — expected 6-digit HOTP values for counters 0..5.
RFC4226_VECTORS = [755224, 287082, 359152, 969429, 338314, 254676]


@tagged("post_install", "-at_install")
class TestTotpAlgorithm(TransactionCase):
    def test_hotp_matches_rfc4226_vectors(self):
        """hotp reproduces the RFC 4226 reference values."""
        for counter, expected in enumerate(RFC4226_VECTORS):
            self.assertEqual(hotp(RFC4226_SECRET, counter), expected)

    def test_match_accepts_current_code(self):
        """A code generated for the current timestep matches its counter."""
        totp = TOTP(RFC4226_SECRET)
        t = 1000 * 30
        code = hotp(RFC4226_SECRET, 1000)
        self.assertEqual(totp.match(code, t=t), 1000)

    def test_match_accepts_previous_step_within_window(self):
        """Slow fingers: the previous step's code stays valid in the window."""
        totp = TOTP(RFC4226_SECRET)
        t = 1000 * 30
        code = hotp(RFC4226_SECRET, 999)
        self.assertEqual(totp.match(code, t=t, window=30), 999)

    def test_match_rejects_wrong_code(self):
        """A code that belongs to no counter in the window returns None."""
        totp = TOTP(RFC4226_SECRET)
        self.assertIsNone(totp.match(123456, t=1000 * 30))

    def test_match_rejects_code_outside_window(self):
        """A stale code far outside the fuzz window is rejected (boundary)."""
        totp = TOTP(RFC4226_SECRET)
        t = 1000 * 30
        stale = hotp(RFC4226_SECRET, 900)
        self.assertIsNone(totp.match(stale, t=t, window=30))
