from odoo import api, fields, models

from .stamping import stamp_encrypted_payload


class CertificateKey(models.Model):
    """Hold ``certificate.key`` material Fernet-encrypted rather than in the clear.

    The base module keeps ``content`` and ``pem_key`` as ``ir.attachment`` rows
    — plaintext files in the filestore — and ``password`` in a ``varchar``
    column. Every field name here is the base module's; only where the bytes
    live changes, so consumers (``l10n_sa_edi``, ``account_edi_proxy_client``,
    ``hr_expense_stripe``, ``l10n_be_hr_payroll``, ``l10n_be_intervat``,
    ``l10n_ar_edi``, …) need no edit.
    """

    _name = "certificate.key"
    _inherit = ["certificate.key", "credential.encryption.mixin"]

    # Walked by credential.credential.action_migrate_encryption_keys to
    # re-encrypt after an ODOO_API_ENCRYPTION_KEY rotation. An encrypted column
    # missing from this tuple becomes permanently undecryptable once the old
    # key env var is retired.
    _ENCRYPTED_FIELD_PAIRS = (
        ("content", "content_encrypted", True),
        ("password", "password_encrypted", False),
    )

    # The encrypted columns stay copyable on purpose: they are what ``copy()``
    # now sees in place of the base module's copyable ``content``/``password``,
    # and marking them copy=False would turn the form's Duplicate action into a
    # silent producer of keys with no material.
    content_encrypted = fields.Binary(
        string="Key file (Encrypted)",
        attachment=False,
        help="Fernet-encrypted key file. The plaintext reaches neither a column nor the filestore.",
    )
    content = fields.Binary(
        compute="_compute_content",
        inverse="_inverse_content",
        store=False,
    )
    password_encrypted = fields.Binary(
        string="Private key password (Encrypted)",
        attachment=False,
    )
    password = fields.Char(
        compute="_compute_password",
        inverse="_inverse_password",
        store=False,
    )
    # Deliberately not stored. The base module persists the normalized PEM of
    # *private* keys as an attachment; recomputing it from the encrypted
    # content costs one key parse and keeps the secret off disk entirely.
    pem_key = fields.Binary(
        compute="_compute_pem_key_plain",
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

    @api.depends("password_encrypted")
    def _compute_password(self):
        self._compute_encrypted_char_field("password_encrypted", "password")

    def _inverse_password(self):
        self._inverse_encrypted_char_field("password", "password_encrypted")

    @api.depends("content_encrypted", "password_encrypted")
    def _compute_pem_key_plain(self):
        for key in self:
            pem_key, _public, _loading_error = self._load_pem_key(
                key.with_context(bin_size=False).content,
                key.password,
            )
            key.pem_key = pem_key

    @api.depends("content_encrypted", "password_encrypted")
    def _compute_pem_key(self):
        """Compute the stored metadata only — ``pem_key`` has its own compute now.

        Overridden rather than delegated to ``super()``: the base method also
        assigns ``pem_key``, and assigning another field's computed value from
        here would make every read of the stored ``public`` flag rewrite it.
        The ``@api.depends`` above unions with the base's along the MRO, so the
        trigger set becomes content/password *and* their encrypted columns.
        """
        for key in self:
            _pem_key, public, loading_error = self._load_pem_key(
                key.with_context(bin_size=False).content,
                key.password,
            )
            key.public = public
            key.loading_error = loading_error
