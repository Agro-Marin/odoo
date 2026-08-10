{
    "name": "Certificate Encryption",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "summary": "Keep certificate and private-key material Fernet-encrypted at rest",
    "description": """
Certificate Encryption
======================

The ``certificate`` module stores its secrets in the clear: ``certificate.key``
keeps the uploaded key file and its normalized PEM form as ``ir.attachment``
rows (plaintext files in the filestore) and the private-key password in a
``varchar`` column; ``certificate.certificate`` does the same for the uploaded
PKCS12 bundle — which embeds a private key — and its password.

This module moves all of that onto ``credential.encryption.mixin``:

* ``certificate.key.content`` / ``.password`` and
  ``certificate.certificate.content`` / ``.pkcs12_password`` become non-stored
  compute/inverse pairs over Fernet-encrypted ``*_encrypted`` columns.
* ``certificate.key.pem_key`` stops being persisted at all — a private key in
  PEM form is the crown-jewel secret, and it is cheap to recompute from the
  encrypted content on demand.
* ``certificate.certificate.pem_certificate`` stays stored: a certificate is
  public by construction, and ``_search_is_valid`` searches on it.

Field *names* are unchanged, so the ~28 relational fields, the twelve modules
that ``_inherit`` these models, and the full ``_sign`` / ``_verify`` /
``_generate_*`` API keep working untouched.

Installing runs a one-shot migration that re-encrypts existing rows and purges
the legacy plaintext (attachments and columns). It therefore requires
``ODOO_API_ENCRYPTION_KEY`` to be set — which is why this ships as a separate
module rather than folded into ``certificate``: an EDI, payroll or sign
deployment that has not provisioned a Fernet key keeps working exactly as
before by simply not installing it.
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": ["certificate", "base_credential_manager"],
    "post_init_hook": "post_init_hook",
}
