"""``CryptContext.verify`` must answer False for a malformed stored hash.

``_MCF_RE`` accepts ``[^$]+`` for the salt and checksum fields, so a string that
merely *looks* like the pbkdf2 MCF format reached ``base64.b64decode`` and raised
``binascii.Error`` out of ``verify()``.  Every login goes through
``ResUsers._check_credentials`` -> ``verify_and_update(password, hashed)`` with
``hashed`` read straight from ``res_users.password``, so one truncated or
hand-edited row turned "wrong password" into an uncaught HTTP 500 on the
unauthenticated login route.
"""

import unittest

from odoo.libs.password import (
    CryptContext,
    _ab64_decode,
    _ab64_encode,
    _parse_hash,
    pbkdf2_sha512_hash,
)

MALFORMED = "$pbkdf2-sha512$1$a$b"
NON_BASE64 = "$pbkdf2-sha512$1$!!!!$!!!!"


class TestMalformedHash(unittest.TestCase):
    def setUp(self):
        self.ctx = CryptContext(schemes=["pbkdf2_sha512", "plaintext"])

    def test_parse_hash_returns_none_instead_of_raising(self):
        self.assertIsNone(_parse_hash(MALFORMED))
        self.assertIsNone(_parse_hash("not a hash at all"))
        self.assertIsNone(_parse_hash(""))

    def test_parse_hash_tolerates_lenient_base64(self):
        self.assertEqual(_parse_hash(NON_BASE64), (1, b"", b""))

    def test_verify_answers_false_for_a_malformed_hash(self):
        for bad in (MALFORMED, NON_BASE64):
            with self.subTest(hash=bad):
                self.assertFalse(self.ctx.verify("whatever", bad))

    def test_verify_and_update_answers_false_for_a_malformed_hash(self):
        for bad in (MALFORMED, NON_BASE64):
            with self.subTest(hash=bad):
                self.assertEqual(
                    self.ctx.verify_and_update("whatever", bad), (False, None)
                )

    def test_a_malformed_hash_does_not_fall_through_to_plaintext(self):
        """A damaged hash must not become a working password.

        ``verify`` falls back to a plaintext comparison for values that were
        never hashed (legacy passwords).  Routing an unparseable *hash* there
        would mean submitting the stored hash string itself logs the user in.
        """
        self.assertFalse(self.ctx.verify(MALFORMED, MALFORMED))
        self.assertFalse(self.ctx.verify(NON_BASE64, NON_BASE64))

    def test_plaintext_fallback_still_applies_to_non_mcf_values(self):
        """The legacy path the fail-closed branch must not disturb."""
        self.assertTrue(self.ctx.verify("legacy-plain", "legacy-plain"))

    def test_real_hashes_still_verify(self):
        hashed = pbkdf2_sha512_hash("s3cret", rounds=1000)
        self.assertTrue(self.ctx.verify("s3cret", hashed))
        self.assertFalse(self.ctx.verify("s3cre", hashed))

    def test_plaintext_scheme_is_unaffected(self):
        self.assertTrue(self.ctx.verify("hunter2", "hunter2"))
        self.assertFalse(self.ctx.verify("hunter2", "hunter3"))


class TestAdaptedBase64Padding(unittest.TestCase):
    """``_ab64_decode`` restores ``-len % 4`` pad chars, not ``4 - len % 4``.

    The old form appended four ``=`` when the length was already a multiple of
    four.  b64decode tolerates the surplus, so the round trip happened to work,
    but the two spellings only agreed by accident.
    """

    def test_round_trip_for_every_length_class(self):
        for size in range(33):
            raw = bytes(range(size))
            with self.subTest(size=size, mod=len(_ab64_encode(raw)) % 4):
                self.assertEqual(_ab64_decode(_ab64_encode(raw)), raw)

    def test_no_surplus_padding_on_aligned_input(self):
        encoded = _ab64_encode(b"abc")
        self.assertEqual(len(encoded) % 4, 0)
        self.assertEqual(_ab64_decode(encoded), b"abc")


if __name__ == "__main__":
    unittest.main()
