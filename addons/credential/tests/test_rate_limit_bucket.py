from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests.common import TransactionCase

from odoo.addons.credential.tools import EndpointRateLimiter


class TestRateLimitBucket(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.MockEndpoint = cls.env["credential.category"]

    def test_bucket_creation(self):
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
                "tokens": 0.0,
            },
        )

        self.assertEqual(bucket.tokens, 0.0)

        bucket.reset_bucket()

        self.assertGreater(bucket.tokens, 0)

    def test_bucket_cleanup(self):
        endpoint = self.MockEndpoint.search([], limit=1)
        if not endpoint:
            endpoint = self.MockEndpoint.create(
                {
                    "name": "Test Endpoint Cleanup",
                    "code": "test_endpoint_cleanup",
                    "storage_hint": "simple",
                },
            )

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

        count = self.env["rate.limit.bucket"].cron_gc_old_buckets()

        self.assertGreaterEqual(count, 1)

        remaining = self.env["rate.limit.bucket"].search([("id", "=", bucket_id)])
        self.assertFalse(remaining)

    def test_bucket_company_rule(self):
        rule = self.env["ir.rule"].search(
            [
                ("model_id.model", "=", "rate.limit.bucket"),
                ("name", "ilike", "multi-company"),
            ],
        )
        self.assertTrue(rule, "Rate limit bucket should have a multi-company rule")


class TestRateLimitBucketTokenConsumption(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.MockEndpoint = cls.env["credential.category"]

    def test_consume_token_success(self):
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

        result = bucket.consume_token()

        self.assertTrue(result)
        bucket.invalidate_recordset()
        self.assertLess(bucket.tokens, initial_tokens)

    def test_consume_token_empty_bucket(self):
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

        result = bucket.consume_token()

        self.assertFalse(result)

    def _make_bucket(self, name):
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
        bucket = self._make_bucket("strict_mode_fail_open")

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
        bucket = self._make_bucket("strict_mode_fail_closed")

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
    def test_endpoint_rate_limiter_reads_strict_flag(self):
        strict_endpoint = SimpleNamespace(
            _name="credential.category",
            id=1,
            rate_limit_enabled=True,
            rate_limit_requests=100,
            rate_limit_period="minute",
            rate_limit_strict=True,
        )
        lax_endpoint = SimpleNamespace(
            _name="credential.category",
            id=2,
            rate_limit_enabled=True,
            rate_limit_requests=100,
            rate_limit_period="minute",
        )

        fake_bucket_model = MagicMock()
        fake_bucket_model.consume_for.return_value = True

        fake_env = MagicMock()
        fake_env.__getitem__.return_value = fake_bucket_model

        limiter = EndpointRateLimiter(fake_env, strict_endpoint)
        limiter.check_limit()
        fake_bucket_model.consume_for.assert_called_with(
            strict_endpoint, None, strict=True
        )

        fake_bucket_model.reset_mock()

        limiter = EndpointRateLimiter(fake_env, lax_endpoint)
        limiter.check_limit()
        fake_bucket_model.consume_for.assert_called_with(
            lax_endpoint, None, strict=False
        )

    def test_consume_for_forwards_strict_to_the_bucket(self):
        endpoint = self.env["credential.category"].create(
            {"name": "consume-for probe", "code": "consume_for_probe"}
        )
        bucket_model = self.env["rate.limit.bucket"]

        with patch.object(type(bucket_model), "get_or_create_bucket") as get_or_create:
            bucket = MagicMock()
            bucket.consume_token.return_value = True
            get_or_create.return_value = bucket

            self.assertTrue(bucket_model.consume_for(endpoint, None, strict=True))
            bucket.consume_token.assert_called_with(strict=True)

            bucket.reset_mock()
            bucket_model.consume_for(endpoint, 7, strict=False)
            bucket.consume_token.assert_called_with(strict=False)
            self.assertEqual(get_or_create.call_args[0][1], 7)
