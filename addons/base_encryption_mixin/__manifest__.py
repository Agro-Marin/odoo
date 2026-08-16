{
    "name": "Encrypted Field Mixin",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "sequence": 5,
    "summary": "Fernet encryption at rest for any model's fields",
    "description": """
Encrypted Field Mixin
=====================

``encryption.mixin`` encrypts named fields at rest with Fernet (AES-128), keyed
from the ``ODOO_API_ENCRYPTION_KEY`` environment variable rather than from the
database. Old keys stay readable through ``ODOO_API_ENCRYPTION_KEY_V<n>`` while
a rotation is in flight, and ``encryption_key_version`` records which key each
row was last written with.

Inherit it and declare ``_ENCRYPTED_FIELD_PAIRS`` -- ``(plain, encrypted,
is_binary)`` per field -- and the compute/inverse pair does the rest. Call
``_stamp_encrypted_payload(vals_list)`` from ``create`` and ``write`` to record
the key version each row was written under; it derives which vals carry
encrypted material from the same tuple, so a consumer cannot stamp something
different from what it declares to the rotation migration.

It carries no notion of what is being encrypted. The models using it today are
a credential vault, an X.509 certificate and its private key, a company's
e-signature material, and a user's API token; only one of those is a
credential, which is why this is not part of the vault that first needed it.
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": [
        "base",
    ],
}
