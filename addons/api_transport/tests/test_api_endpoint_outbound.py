"""Tests for API Endpoint Outbound model."""

from psycopg import IntegrityError

from odoo.exceptions import ValidationError
from odoo.libs.logging import mute_logger
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.api_transport.tools.exceptions import CommError


class TestApiEndpointOutbound(TransactionCase):
    """Test cases for api.endpoint.outbound model."""

    @classmethod
    def setUpClass(cls):
        """Set up test data."""
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")

    def _create_service(self, **kwargs):
        """Helper to create outbound service records."""
        default_vals = {
            "name": "Test Service",
            "code": "test_service",
            "endpoint_url": "https://api.test.com",
            "company_id": self.company.id,
        }
        default_vals.update(kwargs)
        return self.env["api.endpoint.outbound"].create(default_vals)

    def test_create_service(self):
        """Test creating an outbound service."""
        service = self._create_service()

        self.assertEqual(service.name, "Test Service")
        self.assertEqual(service.code, "test_service")
        self.assertEqual(service.endpoint_url, "https://api.test.com")
        self.assertTrue(service.active)

    @mute_logger("odoo.db.cursor")
    def test_code_uniqueness_constraint(self):
        """Test service code must be unique."""
        self._create_service(code="unique_code")

        # Odoo 19's TransactionCase._assertRaises does
        # ``issubclass(exception, AccessError)`` on the first argument,
        # which only accepts a single class — passing a tuple raises
        # ``TypeError: issubclass() arg 1 must be a class``. Catch
        # the DB-level IntegrityError and the Python-level
        # ValidationError explicitly instead.
        try:
            self._create_service(code="unique_code", name="Another Service")
        except IntegrityError, ValidationError:
            pass
        else:
            self.fail("Duplicate service code should raise")

    def test_code_format_validation_valid(self):
        """Test valid code formats."""
        valid_codes = ["simple", "with_underscore", "test123", "api_v1"]

        for i, code in enumerate(valid_codes):
            service = self._create_service(
                code=code,
                name=f"Service {i}",
            )
            self.assertEqual(service.code, code)

    def test_code_format_validation_invalid(self):
        """Test invalid code formats are rejected."""
        invalid_codes = [
            "With-Dash",
            "WithCaps",
            "with spaces",
            "special@char",
        ]

        for code in invalid_codes:
            with self.assertRaises(ValidationError):
                self._create_service(code=code)

    def test_https_enforcement_production(self):
        """Test HTTPS is required for production endpoints."""
        with self.assertRaises(ValidationError):
            self._create_service(
                code="http_service",
                endpoint_url="http://api.test.com",
            )

    @mute_logger("odoo.addons.api_transport.models.api_endpoint_outbound")
    def test_https_enforcement_localhost_allowed(self):
        """Test localhost HTTP is allowed (development)."""
        service = self._create_service(
            code="localhost_service",
            endpoint_url="http://localhost:8080",
        )
        self.assertIn("localhost", service.endpoint_url)

    def test_category_selection(self):
        """Test all category options are valid."""
        categories = [
            "payment",
            "delivery",
            "communication",
            "social",
            "tax",
            "calendar",
            "cloud",
            "ai",
            "geocoding",
            "analytics",
            "odoo_database",
            "other",
        ]

        for i, category in enumerate(categories):
            service = self._create_service(
                code=f"service_{i}",
                name=f"Service {i}",
                category=category,
            )
            self.assertEqual(service.category, category)

    def test_is_odoo_database_compute(self):
        """Test is_odoo_database is computed from category."""
        odoo_service = self._create_service(
            code="odoo_db",
            category="odoo_database",
            odoo_database_name="test_db",
        )
        self.assertTrue(odoo_service.is_odoo_database)

        other_service = self._create_service(
            code="other_svc",
            category="other",
        )
        self.assertFalse(other_service.is_odoo_database)

    def test_is_odoo_database_recomputes_on_category_change(self):
        """t23744: removing the duplicate @api.depends("category") on
        _compute_is_odoo_database must not affect recomputation on write()."""
        service = self._create_service(code="switchable_svc", category="other")
        self.assertFalse(service.is_odoo_database)

        service.write(
            {"category": "odoo_database", "odoo_database_name": "switched_db"}
        )
        self.assertTrue(service.is_odoo_database)

        service.category = "other"
        self.assertFalse(service.is_odoo_database)

    def test_odoo_database_requires_name(self):
        """Test Odoo database service requires database name."""
        with self.assertRaises(ValidationError):
            self._create_service(
                code="odoo_no_name",
                category="odoo_database",
                # Missing odoo_database_name
            )

    def test_environment_selection(self):
        """Test environment selection options."""
        environments = ["test", "staging", "production"]

        for i, env in enumerate(environments):
            service = self._create_service(
                code=f"env_service_{i}",
                name=f"Service {i}",
                environment=env,
            )
            self.assertEqual(service.environment, env)

    def test_request_format_selection(self):
        """Test request format options."""
        formats = ["json", "form", "xml", "graphql"]

        for i, fmt in enumerate(formats):
            service = self._create_service(
                code=f"format_service_{i}",
                name=f"Service {i}",
                request_format=fmt,
            )
            self.assertEqual(service.request_format, fmt)

    def test_timeout_defaults(self):
        """Test default timeout values."""
        service = self._create_service(code="timeout_test")

        self.assertEqual(service.timeout_connect, 10)
        self.assertEqual(service.timeout_read, 30)

    def test_health_check_defaults(self):
        """Test default health check settings."""
        service = self._create_service(code="health_test")

        self.assertTrue(service.health_check_enabled)
        self.assertEqual(service.health_check_interval, 15)
        self.assertTrue(service.is_healthy)

    def test_cache_health_computation_disabled(self):
        """Test cache health when caching disabled."""
        service = self._create_service(
            code="cache_disabled",
            cache_enabled=False,
        )
        self.assertFalse(service.cache_health)

    def test_cache_health_computation_healthy(self):
        """Test cache health with no errors."""
        service = self._create_service(
            code="cache_healthy",
            cache_enabled=True,
            cache_error_count=0,
        )
        self.assertEqual(service.cache_health, "healthy")

    def test_cache_health_computation_degraded(self):
        """Test cache health with few errors."""
        service = self._create_service(
            code="cache_degraded",
            cache_enabled=True,
        )
        service.cache_error_count = 5
        service._compute_cache_health()

        self.assertEqual(service.cache_health, "degraded")

    def test_cache_health_computation_failed(self):
        """Test cache health with many errors."""
        service = self._create_service(
            code="cache_failed",
            cache_enabled=True,
        )
        service.cache_error_count = 15
        service._compute_cache_health()

        self.assertEqual(service.cache_health, "failed")

    def test_credential_count_computation(self):
        """Test credential count is computed correctly."""
        service = self._create_service(code="cred_count_test")

        # Initially no credentials
        self.assertEqual(service.credential_count, 0)

    def test_action_view_credentials(self):
        """Test view credentials action."""
        service = self._create_service(code="view_creds")

        result = service.action_view_credentials()

        self.assertEqual(result["type"], "ir.actions.act_window")
        self.assertEqual(result["res_model"], "credential.credential")
        self.assertIn(str(service.id), str(result["domain"]))

    def test_action_view_logs(self):
        """Test view logs action."""
        service = self._create_service(code="view_logs")

        result = service.action_view_logs()

        self.assertEqual(result["type"], "ir.actions.act_window")
        self.assertEqual(result["res_model"], "api.event.log")
        self.assertIn("outbound", str(result["domain"]))

    def test_action_test_connection_no_credentials(self):
        """Test connection test fails without credentials."""
        service = self._create_service(code="no_creds")

        with self.assertRaises(ValidationError):
            service.action_test_connection()

    def test_oauth_configuration_fields(self):
        """Test OAuth configuration fields exist."""
        service = self._create_service(
            code="oauth_test",
            oauth_client_id="test_client_id",
            oauth_auth_endpoint="https://oauth.test.com/authorize",
            oauth_token_endpoint="https://oauth.test.com/token",
            oauth_scope="read write",
        )

        self.assertEqual(service.oauth_client_id, "test_client_id")
        self.assertEqual(
            service.oauth_auth_endpoint, "https://oauth.test.com/authorize"
        )
        self.assertEqual(service.oauth_scope, "read write")

    def test_log_retention_default(self):
        """Test log retention default value."""
        service = self._create_service(code="retention_test")

        self.assertEqual(service.log_retention_days, 90)


class TestCacheErrorReset(TransactionCase):
    """Test cases for cache error reset cron."""

    @classmethod
    def setUpClass(cls):
        """Set up test data."""
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")

    def test_cron_reset_cache_errors(self):
        """Test cron job resets cache errors."""
        service = self.env["api.endpoint.outbound"].create(
            {
                "name": "Cache Error Service",
                "code": "cache_reset_test",
                "endpoint_url": "https://api.test.com",
                "company_id": self.company.id,
                "cache_enabled": True,
            },
        )

        # Simulate cache errors
        service.write({"cache_error_count": 10})
        self.assertEqual(service.cache_error_count, 10)

        # Run cron
        self.env["api.endpoint.outbound"].cron_reset_cache_errors()

        # Errors should be reset
        self.assertEqual(service.cache_error_count, 0)


class TestStatisticsComputation(TransactionCase):
    """Test cases for service statistics computation."""

    @classmethod
    def setUpClass(cls):
        """Set up test data."""
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")

    def test_statistics_no_logs(self):
        """Test statistics with no event logs."""
        service = self.env["api.endpoint.outbound"].create(
            {
                "name": "Stats Service",
                "code": "stats_test",
                "endpoint_url": "https://api.test.com",
                "company_id": self.company.id,
            },
        )

        self.assertEqual(service.total_requests, 0)
        self.assertEqual(service.success_rate, 0.0)
        self.assertEqual(service.avg_response_time, 0.0)

    def test_statistics_with_logs(self):
        """Test statistics computation with event logs."""
        service = self.env["api.endpoint.outbound"].create(
            {
                "name": "Stats Service 2",
                "code": "stats_test_2",
                "endpoint_url": "https://api.test.com",
                "company_id": self.company.id,
            },
        )

        channel_ref = f"api.endpoint.outbound,{service.id}"

        # Create event logs
        for i in range(10):
            self.env["api.event.log"].create(
                {
                    "direction": "outbound",
                    "channel_id": channel_ref,
                    "status_code": 200 if i < 8 else 500,
                    "duration_ms": 100 + i * 10,
                    "state": "success" if i < 8 else "failed",
                },
            )

        # Refresh statistics
        service._compute_statistics()

        self.assertEqual(service.total_requests, 10)
        self.assertEqual(service.success_rate, 80.0)  # 8/10 * 100
        self.assertTrue(service.avg_response_time > 0)


# NOTE (t23878): TestOutboundSecretKeyRotation was removed with the local
# oauth_client_secret_encrypted column. The OAuth client secret now lives in
# credential.credential; key-rotation coverage for it belongs to core
# (base_credential_manager TestOAuthClientCredentials).


@tagged("post_install", "-at_install")
class TestUnauthenticatedService(TransactionCase):
    """A service with auth_type 'none' needs no credential.

    Requiring one regardless is why unauthenticated integrations stayed on bare
    requests calls: there was no credential to invent, so there was no way in.
    """

    def setUp(self):
        super().setUp()
        self.service = self.env["api.endpoint.outbound"].create(
            {
                "name": "Public Feed",
                "code": "public_feed_probe",
                "endpoint_url": "https://example.invalid/live",
                "endpoint_url_test": "https://example.invalid/test",
                "auth_type": "none",
                "environment": "production",
            }
        )

    def test_client_builds_without_a_credential(self):
        client = self.service._get_api_client()
        self.assertFalse(client.credential)

    def test_no_auth_headers_are_invented(self):
        client = self.service._get_api_client()
        headers = client._build_headers()
        self.assertNotIn("Authorization", headers)

    def test_basic_auth_is_none(self):
        self.assertIsNone(self.service._get_api_client()._get_auth())

    def test_service_environment_picks_the_base_url(self):
        """With no credential to carry it, the service's own environment decides.

        Defaulting to the test URL because an absent credential is not
        "production" would send live traffic somewhere harmless-looking.
        """
        self.assertEqual(
            self.service._get_api_client().base_url, "https://example.invalid/live"
        )

        self.service.environment = "test"
        self.assertEqual(
            self.service._get_api_client().base_url, "https://example.invalid/test"
        )

    def test_authenticated_service_still_demands_a_credential(self):
        """The guard must stay for every service that does authenticate."""
        secured = self.env["api.endpoint.outbound"].create(
            {
                "name": "Secured",
                "code": "secured_probe",
                "endpoint_url": "https://example.invalid",
                "auth_type": "bearer",
            }
        )
        with self.assertRaises(CommError):
            secured._get_api_client()
