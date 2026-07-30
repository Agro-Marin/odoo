"""Tests for credential health validation and certificate DER helpers."""

import base64
import datetime as dt
import os
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class HealthValidationCommon(TransactionCase):
    """Shared fixtures: encryption key patch, categories, PKCS12 builder."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_key = "7ftr9ALjwK7f4IqWwnpFxWx4Wn8vetsznoGT3Oh46eU="
        cls.env_patcher = patch.dict(
            os.environ, {"ODOO_API_ENCRYPTION_KEY": cls.test_key}
        )
        cls.env_patcher.start()
        cls.category_certificate = cls.env.ref(
            "base_credential_manager.credential_category_certificate"
        )
        cls.category_custom = cls.env.ref(
            "base_credential_manager.credential_category_custom"
        )

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    @classmethod
    def _build_pkcs12(cls, password, days_valid=30, days_ago=0):
        """Build a self-signed RSA cert wrapped in password-protected PKCS12.

        :param password: PKCS12 encryption password
        :param days_valid: validity length in days from ``not_valid_before``
        :param days_ago: shift the validity window this many days into the past
        :return: base64-encoded PKCS12 bytes
        :rtype: bytes
        """
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        subject = issuer = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "health-validation-test")],
        )
        start = dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(start)
            .not_valid_after(start + dt.timedelta(days=days_valid))
            .sign(private_key, hashes.SHA256())
        )
        pkcs12_bytes = pkcs12.serialize_key_and_certificates(
            name=b"health-validation-test",
            key=private_key,
            cert=cert,
            cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption(
                password.encode("utf-8"),
            ),
        )
        return base64.b64encode(pkcs12_bytes)

    @classmethod
    def _build_pem_cert(cls, days_valid=30):
        """Build a self-signed certificate as base64-encoded PEM, no key.

        PEM input is the canonical key-less path of _parse_certificate:
        the certificate loads, ``private_key`` stays None.
        """
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        subject = issuer = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "health-validation-test")],
        )
        start = dt.datetime.now(dt.UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(start)
            .not_valid_after(start + dt.timedelta(days=days_valid))
            .sign(private_key, hashes.SHA256())
        )
        return base64.b64encode(cert.public_bytes(serialization.Encoding.PEM))

    @classmethod
    def _make_certificate_credential(cls, name, **builder_kwargs):
        """Create a certificate credential from a fresh self-signed PKCS12."""
        return cls.env["credential.credential"].create(
            {
                "name": name,
                "category_id": cls.category_certificate.id,
                "certificate_content": cls._build_pkcs12(
                    "health-pass", **builder_kwargs
                ),
                "certificate_password": "health-pass",
            },
        )


class TestActionValidateCredential(HealthValidationCommon):
    """Health-status contract of action_validate_credential."""

    def test_non_certificate_category_stays_unknown(self):
        """Without a built-in probe the credential must NOT be marked healthy."""
        credential = self.env["credential.credential"].create(
            {
                "name": "Custom cred without probe",
                "category_id": self.category_custom.id,
            },
        )
        result = credential.action_validate_credential()

        self.assertTrue(result["not_implemented"])
        self.assertFalse(result["success"])
        self.assertIn("No built-in validation", result["message"])
        self.assertEqual(credential.health_status, "unknown")
        self.assertIn("No built-in validation", credential.health_message)
        self.assertTrue(credential.last_health_check)

    def test_valid_certificate_marks_healthy(self):
        """A loadable, in-window certificate with key stamps 'healthy'."""
        credential = self._make_certificate_credential("Valid cert")
        result = credential.action_validate_credential()

        self.assertTrue(result["success"])
        self.assertIn("valid until", result["message"])
        self.assertEqual(credential.health_status, "healthy")
        self.assertTrue(credential.last_health_check)

    def test_expired_certificate_marks_error(self):
        """An out-of-window certificate stamps 'error', never 'healthy'."""
        credential = self._make_certificate_credential(
            "Expired cert", days_valid=10, days_ago=40
        )
        result = credential.action_validate_credential()

        self.assertFalse(result["success"])
        self.assertIn("expired or not yet valid", result["error"])
        self.assertEqual(credential.health_status, "error")

    def test_certificate_without_private_key_marks_error(self):
        """A bare PEM cert (no private key) cannot sign: 'error'."""
        credential = self.env["credential.credential"].create(
            {
                "name": "Keyless PEM cert",
                "category_id": self.category_certificate.id,
                "certificate_content": self._build_pem_cert(),
            },
        )
        result = credential.action_validate_credential()

        self.assertFalse(result["success"])
        self.assertIn("No private key", result["error"])
        self.assertEqual(credential.health_status, "error")


class TestCronValidateCredentials(HealthValidationCommon):
    """Domain filtering and result counting of cron_validate_credentials."""

    def test_cron_counts_and_scopes_by_auto_validate_flag(self):
        """The cron only touches active auto-validate credentials."""
        Credential = self.env["credential.credential"]
        probed_cert = self._make_certificate_credential("Cron cert")
        probed_cert.auto_validate_health = True
        skipped_custom = Credential.create(
            {
                "name": "Cron custom (no probe)",
                "category_id": self.category_custom.id,
                "auto_validate_health": True,
            },
        )
        excluded = Credential.create(
            {
                "name": "Cron excluded",
                "category_id": self.category_custom.id,
                # auto_validate_health keeps its default (False) — the cron
                # domain must leave this record untouched.
            },
        )

        result = Credential.cron_validate_credentials()

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["healthy"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(probed_cert.health_status, "healthy")
        # skipped: probed but without built-in validator → stays unknown
        self.assertEqual(skipped_custom.health_status, "unknown")
        self.assertTrue(skipped_custom.last_health_check)
        # excluded: never probed → no health check stamp at all
        self.assertFalse(excluded.last_health_check)


class TestCertificateDerBytes(HealthValidationCommon):
    """Formatting contract of _get_certificate_der_bytes/_format_bytes."""

    def test_der_bytes_without_certificate_raises_user_error(self):
        """Asking for DER bytes with no certificate loaded must fail loudly."""
        credential = self.env["credential.credential"].create(
            {
                "name": "No cert loaded",
                "category_id": self.category_custom.id,
            },
        )
        with self.assertRaises(UserError):
            credential._get_certificate_der_bytes()

    def test_der_bytes_formats_round_trip(self):
        """raw/base64/encodebytes all encode the same loadable DER blob."""
        credential = self._make_certificate_credential("DER cert")

        raw = credential._get_certificate_der_bytes(formatting="raw")
        cert = x509.load_der_x509_certificate(raw)
        common_names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        self.assertEqual(common_names[0].value, "health-validation-test")

        plain_b64 = credential._get_certificate_der_bytes(formatting="base64")
        self.assertEqual(base64.b64decode(plain_b64), raw)
        self.assertNotIn(b"\n", plain_b64)

        wrapped = credential._get_certificate_der_bytes(formatting="encodebytes")
        self.assertEqual(base64.b64decode(wrapped), raw)
        self.assertIn(b"\n", wrapped)


class TestGetCredentialValueByKey(HealthValidationCommon):
    """Key lookup over the JSON credential payload."""

    def test_key_lookup_returns_value_and_default(self):
        """Present key returns its value; absent key returns the default."""
        credential = self.env["credential.credential"].create(
            {
                "name": "Basic auth for key lookup",
                "category_id": self.env.ref(
                    "base_credential_manager.credential_category_basic_auth"
                ).id,
                "username": "svc-user",
                "password": "svc-pass",
            },
        )
        self.assertEqual(credential.get_credential_value_by_key("username"), "svc-user")
        self.assertEqual(
            credential.get_credential_value_by_key("missing", default="dflt"),
            "dflt",
        )
