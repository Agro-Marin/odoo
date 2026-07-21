"""Tests for rate.limit.bucket model."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests.common import TransactionCase

from odoo.addons.base_credential_manager.tools import EndpointRateLimiter


class TestRateLimitBucket(TransactionCase):
    """Test rate limit bucket model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Use credential.category as the stand-in endpoint: it has the fields
        # (rate_limit_*) the bucket reads.
        cls.MockEndpoint = cls.env["credential.category"]

    def test_bucket_creation(self):
        """Test creating a rate limit bucket."""
        endpoint = self.MockEndpoint.search([], limit=1)
        if not endpoint:
            endpoint = self.MockEndpoint.create(
                {
                    "name": "Test Endpoint",
                    "code": "test_endpoint_bucket",
                    "storage_hint": "simple",
                },
            )

        bucket = self.env["rate.limit.bucket"].create(
            {
                "bucket_key": "test_bucket_key",
                "endpoint_model": endpoint._name,
                "endpoint_id": endpoint.id,
                "tokens": 100.0,
            },
        )

        self.assertEqual(bucket.bucket_key, "test_bucket_key")
        self.assertEqual(bucket.tokens, 100.0)
        self.assertTrue(bucket.last_refill)

    def test_bucket_reset(self):
        """Test resetting a rate limit bucket."""
        endpoint = self.MockEndpoint.search([], limit=1)
        if not endpoint:
            endpoint = self.MockEndpoint.create(
                {
                    "name": "Test Endpoint Reset",
                    "code": "test_endpoint_reset",
                    "storage_hint": "simple",
                },
            )

        bucket = self.env["rate.limit.bucket"].create(
            {
                "bucket_key": "test_bucket_reset",
                "endpoint_model": endpoint._name,
                "endpoint_id": endpoint.id,
                "tokens": 0.0,  # Empty bucket
            },
        )

        self.assertEqual(bucket.tokens, 0.0)

        # Reset should restore to capacity
        bucket.reset_bucket()

        # Tokens should be restored (default capacity from _get_endpoint_config)
        self.assertGreater(bucket.tokens, 0)

    def test_bucket_cleanup(self):
        """Test cleanup of old rate limit buckets."""
        endpoint = self.MockEndpoint.search([], limit=1)
        if not endpoint:
            endpoint = self.MockEndpoint.create(
                {
                    "name": "Test Endpoint Cleanup",
                    "code": "test_endpoint_cleanup",
                    "storage_hint": "simple",
                },
            )

        # Create an old bucket (simulate 31 days ago)
        old_date = fields.Datetime.now() - timedelta(days=31)

        bucket = self.env["rate.limit.bucket"].create(
            {
                "bucket_key": "test_bucket_cleanup_old",
                "endpoint_model": endpoint._name,
                "endpoint_id": endpoint.id,
                "tokens": 100.0,
                "last_request_at": old_date,
            },
        )

        bucket_id = bucket.id

        # Run cleanup
        count = self.env["rate.limit.bucket"].cron_gc_old_buckets()

        # Should have cleaned up at least our old bucket
        self.assertGreaterEqual(count, 1)

        # Bucket should be deleted
        remaining = self.env["rate.limit.bucket"].search([("id", "=", bucket_id)])
        self.assertFalse(remaining)

    def test_bucket_company_rule(self):
        """Test that bucket has company isolation."""
        # Check that the company rule exists
        rule = self.env["ir.rule"].search(
            [
                ("model_id.model", "=", "rate.limit.bucket"),
                ("name", "ilike", "multi-company"),
            ],
        )
        self.assertTrue(rule, "Rate limit bucket should have a multi-company rule")


class TestRateLimitBucketTokenConsumption(TransactionCase):
    """Test rate limit bucket token consumption."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.MockEndpoint = cls.env["credential.category"]

    def test_consume_token_success(self):
        """Test consuming a token when available."""
        endpoint = self.MockEndpoint.search([], limit=1)
        if not endpoint:
            endpoint = self.MockEndpoint.create(
                {
                    "name": "Test Consume",
                    "code": "test_consume_endpoint",
                    "storage_hint": "simple",
                },
            )

        bucket = self.env["rate.limit.bucket"].create(
            {
                "bucket_key": "test_consume_success",
                "endpoint_model": endpoint._name,
                "endpoint_id": endpoint.id,
                "tokens": 10.0,
            },
        )

        initial_tokens = bucket.tokens

        # Consume should succeed
        result = bucket.consume_token()

        self.assertTrue(result)
        bucket.invalidate_recordset()
        # Tokens should have decreased
        self.assertLess(bucket.tokens, initial_tokens)

    def test_consume_token_empty_bucket(self):
        """Test consuming a token when bucket is empty."""
        endpoint = self.MockEndpoint.search([], limit=1)
        if not endpoint:
            endpoint = self.MockEndpoint.create(
                {
                    "name": "Test Consume Empty",
                    "code": "test_consume_empty",
                    "storage_hint": "simple",
                },
            )

        bucket = self.env["rate.limit.bucket"].create(
            {
                "bucket_key": "test_consume_empty",
                "endpoint_model": endpoint._name,
                "endpoint_id": endpoint.id,
                "tokens": 0.0,
            },
        )

        # Consume should fail (no tokens)
        result = bucket.consume_token()

        self.assertFalse(result)

    def _make_bucket(self, name):
        """Create a bucket wired to a dedicated category endpoint."""
        endpoint = self.MockEndpoint.create(
            {
                "name": f"Endpoint for {name}",
                "code": name,
                "storage_hint": "simple",
            },
        )
        return self.env["rate.limit.bucket"].create(
            {
                "bucket_key": name,
                "endpoint_model": endpoint._name,
                "endpoint_id": endpoint.id,
                "tokens": 10.0,
            },
        )

    def test_consume_token_fail_open_on_exception(self):
        """Default (non-strict) mode: internal exception → allow request (S3)."""
        bucket = self._make_bucket("strict_mode_fail_open")

        # Webhook semantics prioritize availability: a bug inside the bucket
        # path must not lock the whole endpoint, so default mode fails open.
        def _explode(self_):
            raise RuntimeError("simulated bucket failure")

        with patch.object(
            type(bucket),
            "_get_endpoint_config",
            _explode,
        ):
            result = bucket.consume_token()
        self.assertTrue(result, "Default mode must fail OPEN (allow request)")

    def test_consume_token_fail_closed_on_exception_strict(self):
        """Strict mode: internal exception → deny request (S3)."""
        bucket = self._make_bucket("strict_mode_fail_closed")

        # Credential-sensitive endpoints opt into strict=True so a rate-limiter
        # bug denies instead of allowing.
        def _explode(self_):
            raise RuntimeError("simulated bucket failure")

        with patch.object(
            type(bucket),
            "_get_endpoint_config",
            _explode,
        ):
            result = bucket.consume_token(strict=True)
        self.assertFalse(result, "Strict mode must fail CLOSED (deny request)")


class TestEndpointRateLimiterStrictMode(TransactionCase):
    """Test that EndpointRateLimiter propagates strict mode from the endpoint."""

    def test_endpoint_rate_limiter_reads_strict_flag(self):
        """EndpointRateLimiter passes strict=True to consume_token when the
        endpoint has a truthy rate_limit_strict, strict=False otherwise."""
        strict_endpoint = SimpleNamespace(
            _name="credential.category",
            id=1,
            enable_rate_limiting=True,
            rate_limit_requests=100,
            rate_limit_period="minute",
            rate_limit_strict=True,
        )
        lax_endpoint = SimpleNamespace(
            _name="credential.category",
            id=2,
            enable_rate_limiting=True,
            rate_limit_requests=100,
            rate_limit_period="minute",
            # rate_limit_strict intentionally absent
        )

        bucket = MagicMock()
        bucket.consume_token.return_value = True

        fake_bucket_model = MagicMock()
        fake_bucket_model.get_or_create_bucket.return_value = bucket

        fake_sudo_target = MagicMock()
        fake_sudo_target.sudo.return_value = fake_bucket_model

        fake_env = MagicMock()
        fake_env.__getitem__.return_value = fake_sudo_target

        # Strict endpoint → strict=True
        limiter = EndpointRateLimiter(fake_env, strict_endpoint)
        limiter.check_limit()
        bucket.consume_token.assert_called_with(strict=True)

        bucket.reset_mock()

        # Lax endpoint → strict=False
        limiter = EndpointRateLimiter(fake_env, lax_endpoint)
        limiter.check_limit()
        bucket.consume_token.assert_called_with(strict=False)
