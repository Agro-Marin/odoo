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
    """`hmac` sudoes itself, so the fake env must answer `env(su=True)`.

    `database.secret` is a server-side secret and never scoped to the reader,
    but `get_param` runs `check_access` and the ACL grants
    `ir.config_parameter` to `group_system` alone -- so before `hmac` sudoed
    internally, every caller had to remember `su=True` and a portal user got an
    AccessError that no admin-run test could reproduce.
    """

    def __init__(self, su=False):
        self.su = su

    def __call__(self, su=False):
        return _FakeEnv(su=su)

    def __getitem__(self, model_name):
        assert model_name == "ir.config_parameter"
        assert self.su, "hmac must read database.secret with sudo"
        return _FakeConfigParam()


class _FakeRecord:
    _name = "res.partner"
    id = 42

    def ensure_one(self):
        return self

    def __call__(self, su=False):
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
        self.assertIs(self._verify("é"), False)
        self.assertIs(self._verify("deadbeefo1f4é"), False)

    def test_non_hex_timestamp_returns_false(self):
        self.assertIs(self._verify("deadbeefonot-hex"), False)

    def test_missing_timestamp_separator_returns_false(self):
        self.assertIs(self._verify("deadbeef"), False)

    def test_out_of_range_timestamp_returns_false(self):
        self.assertIs(self._verify("deadbeefo" + "f" * 32), False)

    def test_non_string_token_returns_false(self):
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
        token = limited_field_access_token(
            self.record, "image_128", hex(1), scope="binary"
        )
        self.assertIs(self._verify(token), False)


if __name__ == "__main__":
    unittest.main()
