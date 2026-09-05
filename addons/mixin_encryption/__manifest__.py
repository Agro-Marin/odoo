{
    "name": "Encrypted Field Mixin",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "sequence": 5,
    "summary": "Fernet encryption at rest for any model's fields",
    "description": """
Encrypted Field Mixin
=====================

``mixin.encryption`` encrypts named fields at rest with Fernet (AES-128), keyed
from the ``ODOO_API_ENCRYPTION_KEY`` environment variable rather than from the
database. Old keys stay readable through ``ODOO_API_ENCRYPTION_KEY_V<n>`` while
a rotation is in flight, and ``encryption_key_version`` records which key each
row was last written with.

Inherit it, declare ``_ENCRYPTED_FIELD_PAIRS`` -- ``(plain, encrypted,
is_binary)`` per field -- and write your own compute/inverse pair using the
mixin's ``_decrypt_value``/``_encrypt_value``/``_decrypt_binary_value``/
``_encrypt_binary_value``/``_decrypt_value_safe`` primitives; the tuple itself
only drives the generic reencryption and key-version-stamping helpers
(``_reencrypt_with_current_key``, ``_get_encryption_migration_models``), not a
field's ``compute=``/``inverse=`` -- there is no automatic wiring from the
tuple to those. Call ``_stamp_encrypted_payload(vals_list)`` from ``create``
and ``write`` to record the key version each row was written under; it derives
which vals carry encrypted material from the same tuple, so a consumer cannot
stamp something different from what it declares to the rotation migration.

It carries no notion of what is being encrypted. Consumers today span all four
clones of this fork; ``_get_encryption_migration_models()`` returns the live
list within one database.
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": [
        "base",
    ],
}
