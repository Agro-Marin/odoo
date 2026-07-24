"""Regression tests for ``odoo.tools.security.verify_limited_field_access_token``.

``access_token`` is attacker-controllable (``/web/content`` is ``auth="public"``,
mail mention tokens arrive in a JSON body, presence tokens over the websocket),
so every malformed shape must be a plain ``False``, never an exception.

The non-ASCII case used to escape as ``TypeError: comparing strings with
non-ASCII characters is not supported`` out of ``hmac.compare_digest`` and
surfaced as an HTTP 500 on an unauthenticated request.
"""

import unittest

from odoo.tools.security import (
    limited_field_access_token,
    verify_limited_field_access_token,
)


class _FakeConfigParam:
    def get_param(self, key):
        assert key == "database.secret"
        return "s3cr3t-test-key"


class _FakeEnv:
    def __getitem__(self, model_name):
        assert model_name == "ir.config_parameter"
        return _FakeConfigParam()


class _FakeRecord:
    """Minimal stand-in for the BaseModel surface the token helpers touch."""

    _name = "res.partner"
    id = 42

    def ensure_one(self):
        return self

    def __call__(self, su=False):  # record.env(su=True)
        return _FakeEnv()

    @property
    def env(self):
        return self


class TestVerifyLimitedFieldAccessToken(unittest.TestCase):
    def setUp(self):
        self.record = _FakeRecord()

    def _verify(self, token):
        return verify_limited_field_access_token(
            self.record, "image_128", token, scope="binary"
        )

    def test_valid_token_verifies(self):
        token = limited_field_access_token(self.record, "image_128", scope="binary")
        self.assertTrue(self._verify(token))

    def test_non_ascii_token_returns_false(self):
        # Was: TypeError out of hmac.compare_digest -> HTTP 500.
        self.assertIs(self._verify("é"), False)
        self.assertIs(self._verify("deadbeefo1f4é"), False)

    def test_non_hex_timestamp_returns_false(self):
        self.assertIs(self._verify("deadbeefonot-hex"), False)

    def test_missing_timestamp_separator_returns_false(self):
        self.assertIs(self._verify("deadbeef"), False)

    def test_out_of_range_timestamp_returns_false(self):
        # int(..., 16) succeeds, datetime.fromtimestamp() cannot represent it.
        self.assertIs(self._verify("deadbeefo" + "f" * 32), False)

    def test_non_string_token_returns_false(self):
        # A JSON body / websocket payload can carry null, an int, or a list.
        for token in (None, 123, [], {}, b"deadbeefo1f4"):
            with self.subTest(token=token):
                self.assertIs(self._verify(token), False)

    def test_empty_token_returns_false(self):
        self.assertIs(self._verify(""), False)

    def test_wrong_scope_returns_false(self):
        token = limited_field_access_token(self.record, "image_128", scope="binary")
        self.assertIs(
            verify_limited_field_access_token(
                self.record, "image_128", token, scope="other"
            ),
            False,
        )

    def test_expired_token_returns_false(self):
        # hex timestamp in the past -> signature matches, expiry check fails.
        token = limited_field_access_token(
            self.record, "image_128", hex(1), scope="binary"
        )
        self.assertIs(self._verify(token), False)


if __name__ == "__main__":
    unittest.main()
