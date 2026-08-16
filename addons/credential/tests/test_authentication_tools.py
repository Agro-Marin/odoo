import hashlib
import hmac
import time
from datetime import UTC, datetime

from odoo.tests import TransactionCase, tagged

from odoo.addons.credential.tools.authentication import (
    verify_bearer_token,
    verify_hmac_signature,
    verify_signature,
    verify_timestamp,
)


@tagged("post_install", "-at_install")
class TestAuthenticationTools(TransactionCase):
    @staticmethod
    def _hex(secret, body, hash_func=hashlib.sha256):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        return hmac.new(secret.encode("utf-8"), raw, hash_func).hexdigest()

    def test_bearer_valid(self):
        self.assertTrue(
            verify_bearer_token({"Authorization": "Bearer tok-123"}, "tok-123")
        )

    def test_bearer_rejects_mismatch(self):
        self.assertFalse(
            verify_bearer_token({"Authorization": "Bearer wrong"}, "tok-123")
        )

    def test_bearer_rejects_non_dict_headers(self):
        self.assertFalse(verify_bearer_token("not-a-dict", "tok"))

    def test_bearer_rejects_missing_prefix(self):
        self.assertFalse(verify_bearer_token({"Authorization": "Basic x"}, "tok"))

    def test_bearer_rejects_empty_token_and_expected(self):
        self.assertFalse(verify_bearer_token({"Authorization": "Bearer   "}, "tok"))
        self.assertFalse(verify_bearer_token({"Authorization": "Bearer tok"}, ""))

    def test_hmac_valid_str_body(self):
        body = '{"event":"ping"}'
        headers = {"X-Hub-Signature-256": "sha256=" + self._hex("shh", body)}
        self.assertTrue(verify_hmac_signature(headers, body, "shh", hashlib.sha256))

    def test_hmac_valid_bytes_body(self):
        body = b'{"event":"ping"}'
        headers = {"X-Hub-Signature-256": "sha256=" + self._hex("shh", body)}
        self.assertTrue(verify_hmac_signature(headers, body, "shh", hashlib.sha256))

    def test_hmac_rejects_wrong_secret(self):
        body = "payload"
        headers = {"X-Hub-Signature-256": "sha256=" + self._hex("shh", body)}
        self.assertFalse(verify_hmac_signature(headers, body, "other", hashlib.sha256))

    def test_hmac_rejects_bad_inputs(self):
        self.assertFalse(verify_hmac_signature("x", "b", "s", hashlib.sha256))
        self.assertFalse(verify_hmac_signature({}, "b", "s", hashlib.sha256))
        self.assertFalse(
            verify_hmac_signature(
                {"X-Hub-Signature-256": "sha256=ab"}, "b", "", hashlib.sha256
            )
        )
        self.assertFalse(
            verify_hmac_signature(
                {"X-Hub-Signature-256": "sha256=zzz"}, "b", "s", hashlib.sha256
            )
        )

    def test_verify_signature_bearer(self):
        self.assertTrue(
            verify_signature("bearer", {"Authorization": "Bearer k"}, "", secret="k")
        )

    def test_verify_signature_hmac_256_and_512(self):
        body = "abc"
        self.assertTrue(
            verify_signature(
                "hmac_sha256",
                {"X-Hub-Signature-256": "sha256=" + self._hex("s", body)},
                body,
                secret="s",
            )
        )
        self.assertTrue(
            verify_signature(
                "hmac_sha512",
                {
                    "X-Hub-Signature-512": "sha512="
                    + self._hex("s", body, hashlib.sha512)
                },
                body,
                secret="s",
            )
        )

    def test_verify_signature_unknown_and_custom_without_method(self):
        self.assertFalse(verify_signature("bogus", {}, ""))
        self.assertFalse(verify_signature("custom", {}, ""))

    def test_timestamp_valid_epoch_int_and_str(self):
        now = int(time.time())
        self.assertTrue(verify_timestamp(now))
        self.assertTrue(verify_timestamp(str(now)))

    def test_timestamp_valid_iso(self):
        self.assertTrue(verify_timestamp(datetime.now(tz=UTC).isoformat()))

    def test_timestamp_rejects_out_of_bounds(self):
        self.assertFalse(verify_timestamp(-1))
        self.assertFalse(verify_timestamp(253402300800))

    def test_timestamp_rejects_too_old(self):
        self.assertFalse(
            verify_timestamp(int(time.time()) - 10_000, max_age_seconds=300)
        )

    def test_timestamp_rejects_future(self):
        self.assertFalse(
            verify_timestamp(int(time.time()) + 10_000, future_tolerance_seconds=5)
        )

    def test_timestamp_rejects_invalid_type(self):
        self.assertFalse(verify_timestamp(None))
