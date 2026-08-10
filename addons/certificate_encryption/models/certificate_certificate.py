from odoo import api, fields, models

from .stamping import stamp_encrypted_payload


class CertificateCertificate(models.Model):
    """Hold the uploaded certificate bundle and its password Fernet-encrypted.

    ``content`` matters because a PKCS12 bundle embeds the private key: the
    base module writes it to the filestore in the clear. ``pem_certificate``
    stays stored and unencrypted on purpose — a certificate is public by
    construction, and ``_search_is_valid`` searches on it.
    """

    _name = "certificate.certificate"
    _inherit = ["certificate.certificate", "credential.encryption.mixin"]

    _ENCRYPTED_FIELD_PAIRS = (
        ("content", "content_encrypted", True),
        ("pkcs12_password", "pkcs12_password_encrypted", False),
    )

    # Copyable, like the base module's plaintext columns they replace — see the
    # note in certificate_key.py.
    content_encrypted = fields.Binary(
        string="Certificate (Encrypted)",
        attachment=False,
        help="Fernet-encrypted certificate file. A PKCS12 bundle carries a private key, "
        "so the plaintext reaches neither a column nor the filestore.",
    )
    content = fields.Binary(
        compute="_compute_content",
        inverse="_inverse_content",
        store=False,
    )
    pkcs12_password_encrypted = fields.Binary(
        string="Certificate Password (Encrypted)",
        attachment=False,
    )
    pkcs12_password = fields.Char(
        compute="_compute_pkcs12_password",
        inverse="_inverse_pkcs12_password",
        store=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        stamp_encrypted_payload(records, vals_list)
        return records

    def write(self, vals):
        result = super().write(vals)
        stamp_encrypted_payload(self, [vals] * len(self))
        return result

    @api.depends("content_encrypted")
    def _compute_content(self):
        self._compute_encrypted_binary_field("content_encrypted", "content")

    def _inverse_content(self):
        self._inverse_encrypted_binary_field("content", "content_encrypted")

    @api.depends("pkcs12_password_encrypted")
    def _compute_pkcs12_password(self):
        self._compute_encrypted_char_field(
            "pkcs12_password_encrypted",
            "pkcs12_password",
        )

    def _inverse_pkcs12_password(self):
        self._inverse_encrypted_char_field(
            "pkcs12_password",
            "pkcs12_password_encrypted",
        )

    @api.depends("content_encrypted", "pkcs12_password_encrypted")
    def _compute_pem_certificate(self):
        """Retrigger the base compute off the encrypted columns.

        The base declares ``@api.depends('content', 'pkcs12_password')``; both
        are now non-stored computes, so the union added here is what actually
        fires when a new upload lands in ``content_encrypted``.
        """
        return super()._compute_pem_certificate()
