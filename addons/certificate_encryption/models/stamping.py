"""Record which Fernet key a row's ciphertext was written under.

``credential.credential`` does this in its own create/write overrides, off a
hand-maintained field list. Here it is derived from ``_ENCRYPTED_FIELD_PAIRS``
instead, so the two certificate models cannot drift out of sync with what they
declare to the rotation migration.

Unstamped rows are not *wrong* — ``action_migrate_encryption_keys`` treats a
NULL version as eligible and re-encrypts them — but every certificate in the
database would then be rewritten on every rotation, forever.

A module-level function rather than a mixin class: Odoo rebuilds model classes
by reassigning ``__bases__``, which rejects a plain Python base in the MRO, and
an ``AbstractModel`` would leave the create/write override order implicit.
"""


def stamp_encrypted_payload(records, vals_list):
    """Stamp the records whose vals actually carried encrypted material.

    :param records: the recordset just created or written
    :param vals_list: the vals dicts, positionally aligned with *records*
    """
    if not records:
        return
    plain_fields = {plain for plain, _enc, _binary in records._ENCRYPTED_FIELD_PAIRS}
    to_stamp = records.browse()
    for record, vals in zip(records, vals_list, strict=False):
        if plain_fields & set(vals):
            to_stamp |= record
    if not to_stamp:
        return
    version = records._get_current_encryption_key_version()
    if not version:
        return
    # The stamp is raw SQL; the inverses that produced the ciphertext are still
    # pending in the ORM, and an UPDATE that races their flush is discarded.
    records.env.cr.flush()
    to_stamp._stamp_encryption_key_version(version)
