import base64
from datetime import UTC, datetime, timedelta

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from odoo.tests import TransactionCase, tagged

from odoo.addons.certificate.tools import CertificateAdapter


@tagged("post_install", "-at_install")
class TestCertificateAdapter(TransactionCase):
    """`CertificateAdapter.get_connection_with_tls_context` patches
    `ssl_context.load_cert_chain` to pull the certificate and its private
    key straight out of a `certificate.certificate` record; it must be able
    to unlock a password-protected private key the same way `certificate.key`
    itself does everywhere else (`_sign`, `_decrypt`, `_get_unencrypted_pem_key`).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        crypto_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.key = cls.env["certificate.key"].create(
            {
                "name": "Adapter test key (password-protected)",
                "content": base64.b64encode(
                    crypto_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.BestAvailableEncryption(
                            b"hunter2"
                        ),
                    )
                ),
                "password": "hunter2",
            }
        )

        subject = issuer = x509.Name(
            [x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "adapter.test")]
        )
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(crypto_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(UTC) - timedelta(days=1))
            .not_valid_after(datetime.now(UTC) + timedelta(days=1))
            .sign(crypto_key, hashes.SHA256())
        )
        cls.certificate = cls.env["certificate.certificate"].create(
            {
                "name": "Adapter test certificate",
                "content": base64.b64encode(
                    certificate.public_bytes(encoding=serialization.Encoding.PEM)
                ),
                "private_key_id": cls.key.id,
            }
        )

    def _ssl_context(self):
        adapter = CertificateAdapter()
        request = requests.PreparedRequest()
        request.prepare(method="GET", url="https://example.com")
        conn = adapter.get_connection_with_tls_context(request, True)
        return conn.conn_kw["ssl_context"]

    def test_load_cert_chain_unlocks_a_password_protected_key(self):
        context = self._ssl_context()
        # Must not raise: the certificate's private key is password-protected,
        # and load_cert_chain has to use that password to unlock it.
        context.load_cert_chain(self.certificate)
