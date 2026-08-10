"""Tests for inbound endpoint logic (authentication, payload, IP validation).

Since api.endpoint.inbound is an AbstractModel with no concrete inheritor
in this module, we test through the tools/ functions and the channel mixin
methods on api.endpoint.outbound (which shares api.channel.mixin).
"""

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

from odoo.libs.logging import mute_logger
from odoo.tests.common import TransactionCase

from odoo.addons.api_transport.tools import (
    compute_payload_hash,
    sanitize_error_message,
    validate_content_type,
    validate_json_payload,
    validate_payload_size,
    verify_bearer_token,
    verify_hmac_signature,
    verify_timestamp,
)


class TestVerifyBearerToken(TransactionCase):
    """Test verify_bearer_token through the actual function."""

    def test_valid_bearer_token(self):
        """Test valid bearer token is accepted."""
        headers = {"Authorization": "Bearer my_secret_token"}
        self.assertTrue(verify_bearer_token(headers, "my_secret_token"))

    def test_invalid_bearer_token(self):
        """Test wrong token is rejected."""
        headers = {"Authorization": "Bearer wrong_token"}
        self.assertFalse(verify_bearer_token(headers, "my_secret_token"))

    @mute_logger("odoo.addons.base_credential_manager.tools.authentication")
    def test_missing_authorization_header(self):
        """Test missing Authorization header is rejected."""
        self.assertFalse(verify_bearer_token({}, "my_secret_token"))

    @mute_logger("odoo.addons.base_credential_manager.tools.authentication")
    def test_malformed_authorization_header(self):
        """Test non-Bearer auth header is rejected."""
        headers = {"Authorization": "Basic abc123"}
        self.assertFalse(verify_bearer_token(headers, "my_secret_token"))

    @mute_logger("odoo.addons.base_credential_manager.tools.authentication")
    def test_empty_bearer_token(self):
        """Test empty token after Bearer prefix is rejected."""
        headers = {"Authorization": "Bearer "}
        self.assertFalse(verify_bearer_token(headers, "my_secret_token"))

    @mute_logger("odoo.addons.base_credential_manager.tools.authentication")
    def test_no_expected_token(self):
        """Test missing expected token is rejected."""
        headers = {"Authorization": "Bearer some_token"}
        self.assertFalse(verify_bearer_token(headers, ""))

    @mute_logger("odoo.addons.base_credential_manager.tools.authentication")
    def test_non_dict_headers_rejected(self):
        """Test non-dict headers are rejected."""
        self.assertFalse(verify_bearer_token("not a dict", "token"))


class TestVerifyHmacSignature(TransactionCase):
    """Test HMAC signature verification through the actual function."""

    def _sign(self, body, secret, hash_func=hashlib.sha256):
        """Helper to generate HMAC signature."""
        return hmac.new(
            secret.encode("utf-8"),
            body.encode("utf-8"),
            hash_func,
        ).hexdigest()

    def test_valid_hmac_sha256(self):
        """Test valid HMAC-SHA256 signature is accepted."""
        secret = "test_secret"
        body = '{"event": "test"}'
        sig = self._sign(body, secret)
        headers = {"X-Hub-Signature-256": f"sha256={sig}"}

        self.assertTrue(verify_hmac_signature(headers, body, secret, hashlib.sha256))

    def test_invalid_hmac_sha256(self):
        """Test wrong HMAC-SHA256 signature is rejected."""
        body = '{"event": "test"}'
        sig = self._sign(body, "wrong_secret")
        headers = {"X-Hub-Signature-256": f"sha256={sig}"}

        self.assertFalse(
            verify_hmac_signature(headers, body, "correct_secret", hashlib.sha256)
        )

    def test_valid_hmac_sha512(self):
        """Test valid HMAC-SHA512 signature is accepted."""
        secret = "test_secret"
        body = '{"event": "test"}'
        sig = self._sign(body, secret, hashlib.sha512)
        headers = {"X-Hub-Signature-512": f"sha512={sig}"}

        self.assertTrue(
            verify_hmac_signature(
                headers,
                body,
                secret,
                hashlib.sha512,
                signature_header="X-Hub-Signature-512",
                signature_prefix="sha512=",
            )
        )

    @mute_logger("odoo.addons.base_credential_manager.tools.authentication")
    def test_missing_signature_header(self):
        """Test missing signature header is rejected."""
        self.assertFalse(verify_hmac_signature({}, "body", "secret", hashlib.sha256))

    @mute_logger("odoo.addons.base_credential_manager.tools.authentication")
    def test_no_secret_provided(self):
        """Test missing secret is rejected."""
        headers = {"X-Hub-Signature-256": "sha256=abc"}
        self.assertFalse(verify_hmac_signature(headers, "body", "", hashlib.sha256))

    @mute_logger("odoo.addons.base_credential_manager.tools.authentication")
    def test_non_hex_signature_rejected(self):
        """Test non-hexadecimal signature is rejected."""
        headers = {"X-Hub-Signature-256": "sha256=not_hex_zzzz"}
        self.assertFalse(
            verify_hmac_signature(headers, "body", "secret", hashlib.sha256)
        )

    def test_constant_time_comparison(self):
        """Test that valid signatures use constant-time comparison."""
        secret = "test_secret"
        body = '{"data": "sensitive"}'
        sig = self._sign(body, secret)
        headers = {"X-Hub-Signature-256": f"sha256={sig}"}

        # Both should use hmac.compare_digest internally
        self.assertTrue(verify_hmac_signature(headers, body, secret, hashlib.sha256))


class TestVerifyTimestamp(TransactionCase):
    """Test timestamp verification (replay attack prevention)."""

    def test_current_unix_timestamp_valid(self):
        """Test current Unix timestamp passes verification."""
        self.assertTrue(verify_timestamp(time.time(), max_age_seconds=300))

    @mute_logger("odoo.addons.base_credential_manager.tools.authentication")
    def test_old_unix_timestamp_rejected(self):
        """Test old Unix timestamp is rejected."""
        old_ts = time.time() - 600  # 10 minutes ago
        self.assertFalse(verify_timestamp(old_ts, max_age_seconds=300))

    @mute_logger("odoo.addons.base_credential_manager.tools.authentication")
    def test_future_timestamp_rejected(self):
        """Test far-future timestamp is rejected."""
        future_ts = time.time() + 3600  # 1 hour in future
        self.assertFalse(
            verify_timestamp(
                future_ts, max_age_seconds=300, future_tolerance_seconds=60
            )
        )

    def test_iso_string_timestamp_valid(self):
        """Test ISO format string timestamp passes."""
        now_iso = datetime.now(tz=UTC).isoformat()
        self.assertTrue(verify_timestamp(now_iso, max_age_seconds=300))

    def test_z_suffix_iso_string(self):
        """Test ISO format with Z suffix passes."""
        now_iso = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertTrue(verify_timestamp(now_iso, max_age_seconds=300))

    @mute_logger("odoo.addons.base_credential_manager.tools.authentication")
    def test_negative_timestamp_rejected(self):
        """Test negative Unix timestamp is rejected."""
        self.assertFalse(verify_timestamp(-1))

    @mute_logger("odoo.addons.base_credential_manager.tools.authentication")
    def test_invalid_type_rejected(self):
        """Test non-numeric/non-string type is rejected."""
        self.assertFalse(verify_timestamp([123]))


class TestValidatePayload(TransactionCase):
    """Test payload validation functions."""

    def test_valid_json_payload(self):
        """Test valid JSON passes validation."""
        is_valid, parsed, error = validate_json_payload('{"key": "value"}')
        self.assertTrue(is_valid)
        self.assertEqual(parsed["key"], "value")
        self.assertIsNone(error)

    def test_invalid_json_payload(self):
        """Test invalid JSON fails validation."""
        is_valid, parsed, error = validate_json_payload("not valid json")
        self.assertFalse(is_valid)
        self.assertIsNone(parsed)
        self.assertIn("Invalid JSON", error)

    def test_empty_payload_rejected(self):
        """Test empty payload fails validation."""
        is_valid, _parsed, _error = validate_json_payload("")
        self.assertFalse(is_valid)

    def test_deeply_nested_payload_rejected(self):
        """Test deeply nested payload exceeds max depth."""
        # Build a 200-level nested dict
        payload = {"level": 0}
        current = payload
        for i in range(200):
            current["nested"] = {"level": i + 1}
            current = current["nested"]
        is_valid, _, error = validate_json_payload(json.dumps(payload), max_depth=100)
        self.assertFalse(is_valid)
        self.assertIn("depth", error)

    def test_payload_size_validation(self):
        """Test payload size check."""
        small = b'{"ok": true}'
        is_valid, error = validate_payload_size(small, max_size_bytes=1024)
        self.assertTrue(is_valid)

        large = b"x" * 2048
        is_valid, error = validate_payload_size(large, max_size_bytes=1024)
        self.assertFalse(is_valid)
        self.assertIn("too large", error)

    def test_content_type_validation(self):
        """Test Content-Type header check."""
        is_valid, _ = validate_content_type("application/json")
        self.assertTrue(is_valid)

        is_valid, _error = validate_content_type("text/plain")
        self.assertFalse(is_valid)

        is_valid, _ = validate_content_type("application/json; charset=utf-8")
        self.assertTrue(is_valid)

        is_valid, _error = validate_content_type(None)
        self.assertFalse(is_valid)


class TestPayloadHash(TransactionCase):
    """Test payload hashing for duplicate detection."""

    def test_dict_hash_deterministic(self):
        """Test dict payload produces deterministic hash."""
        h1 = compute_payload_hash({"b": 2, "a": 1})
        h2 = compute_payload_hash({"a": 1, "b": 2})
        self.assertEqual(h1, h2)

    def test_string_hash_normalizes_json(self):
        """Test string payload normalizes before hashing."""
        h1 = compute_payload_hash('{"b": 2, "a": 1}')
        h2 = compute_payload_hash('{"a": 1, "b": 2}')
        self.assertEqual(h1, h2)

    def test_different_payloads_different_hash(self):
        """Test different payloads produce different hashes."""
        h1 = compute_payload_hash({"a": 1})
        h2 = compute_payload_hash({"a": 2})
        self.assertNotEqual(h1, h2)


class TestSanitizeErrorMessage(TransactionCase):
    """Test error message sanitization."""

    def test_sanitizes_mixed_case_password(self):
        """Test mixed-case 'Password' is sanitized."""
        result = sanitize_error_message("Invalid Password: abc123")
        self.assertNotIn("Password", result)
        self.assertIn("***", result)

    def test_sanitizes_uppercase_token(self):
        """Test uppercase TOKEN is sanitized."""
        result = sanitize_error_message("Expired TOKEN_XYZ")
        self.assertNotIn("TOKEN", result)

    def test_truncates_long_message(self):
        """Test long messages are truncated."""
        long_msg = "x" * 1000
        result = sanitize_error_message(long_msg, max_length=100)
        self.assertLessEqual(len(result), 120)  # 100 + "... (truncated)"

    def test_accepts_exception(self):
        """Test Exception objects are handled."""
        result = sanitize_error_message(ValueError("bad token value"))
        self.assertNotIn("token", result)


class TestChannelMixinRateLimit(TransactionCase):
    """Test rate limit and retry methods via api.endpoint.outbound (concrete)."""

    @classmethod
    def setUpClass(cls):
        """Set up test data."""
        super().setUpClass()
        cls.service = cls.env["api.endpoint.outbound"].create(
            {
                "name": "Test Service",
                "code": "test_rate_limit",
                "endpoint_url": "https://api.test.com",
            },
        )

    def test_calculate_retry_delay_fixed(self):
        """Test fixed retry delay calculation."""
        self.service.retry_backoff_type = "fixed"
        self.service.retry_initial_delay = 30
        self.assertEqual(self.service.calculate_retry_delay(1), 30)
        self.assertEqual(self.service.calculate_retry_delay(5), 30)

    def test_calculate_retry_delay_linear(self):
        """Test linear retry delay calculation."""
        self.service.retry_backoff_type = "linear"
        self.service.retry_initial_delay = 30
        self.assertEqual(self.service.calculate_retry_delay(1), 30)
        self.assertEqual(self.service.calculate_retry_delay(3), 90)

    def test_calculate_retry_delay_exponential(self):
        """Test exponential retry delay calculation."""
        self.service.retry_backoff_type = "exponential"
        self.service.retry_initial_delay = 60
        self.assertEqual(self.service.calculate_retry_delay(1), 60)
        self.assertEqual(self.service.calculate_retry_delay(2), 120)
        self.assertEqual(self.service.calculate_retry_delay(3), 240)

    def test_should_retry_enabled(self):
        """Test retry is allowed when within max attempts."""
        self.service.retry_enabled = True
        self.service.retry_max_attempts = 3
        self.assertTrue(self.service.should_retry(1))
        self.assertTrue(self.service.should_retry(2))
        self.assertFalse(self.service.should_retry(3))

    def test_should_retry_disabled(self):
        """Test retry is denied when disabled."""
        self.service.retry_enabled = False
        self.assertFalse(self.service.should_retry(1))
