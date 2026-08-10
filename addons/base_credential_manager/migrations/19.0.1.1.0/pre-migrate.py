"""Retire credential.credential's duplicate certificate implementation.

X.509 material belongs to ``certificate.certificate`` / ``certificate.key``,
which own the parsing, the cert/key compatibility constraint and the full
signing API. This model carried a second, partial copy of that; it is removed.

Runs pre-migration because both fixups have to land *before* the data files
load: ``category_id`` is ``ondelete='restrict'``, so the obsolete
``credential_category_certificate`` record cannot be dropped while a credential
still points at it, and ``storage_hint`` loses its ``certificate`` selection
value in this same version.

Pure SQL, no ORM: a module's pre-migration runs before its own models are set
up in the registry, so ``env['credential.category']`` is a KeyError here.

The ``certificate_*`` / ``private_key_*`` columns are deliberately NOT dropped.
Removing the Python fields already makes them inert, and leaving the ciphertext
in place keeps a recovery path for any deployment whose material was not moved
by ``remote_machines``'s own migration. Dropping them is a separate, later
change, once operators have confirmed the move.
"""

import logging

from odoo.db.schema import column_exists

_logger = logging.getLogger(__name__)

_MODULE = "base_credential_manager"


def _xml_id_res_id(cr, name):
    cr.execute(
        "SELECT res_id FROM ir_model_data WHERE module = %s AND name = %s",
        (_MODULE, name),
    )
    row = cr.fetchone()
    return row[0] if row else None


def migrate(cr, version):
    """:param cr: database cursor.
    :param str version: module version being upgraded from.
    """
    certificate_category_id = _xml_id_res_id(cr, "credential_category_certificate")
    fallback_id = _xml_id_res_id(cr, "credential_category_custom")

    if certificate_category_id and fallback_id:
        cr.execute(
            "UPDATE credential_credential SET category_id = %s WHERE category_id = %s",
            (fallback_id, certificate_category_id),
        )
        if cr.rowcount:
            _logger.info(
                "base_credential_manager: moved %d credential(s) off the retired "
                "'certificate' category onto 'custom'",
                cr.rowcount,
            )

        # Dropping the record from the data file is not enough: the file is
        # noupdate="1", and Odoo deliberately never garbage-collects noupdate
        # records on update. Left alone, a "Certificate" category would keep
        # inviting users to file X.509 material somewhere that no longer
        # stores it. Guarded on emptiness so a consumer model with its own FK
        # to the category cannot be orphaned by this.
        cr.execute(
            "DELETE FROM credential_category WHERE id = %s AND NOT EXISTS ("
            "    SELECT 1 FROM credential_credential WHERE category_id = %s"
            ")",
            (certificate_category_id, certificate_category_id),
        )
        if cr.rowcount:
            cr.execute(
                "DELETE FROM ir_model_data WHERE module = %s AND name = %s",
                (_MODULE, "credential_category_certificate"),
            )
            _logger.info(
                "base_credential_manager: removed the retired 'certificate' category",
            )
        else:
            _logger.warning(
                "base_credential_manager: the 'certificate' category (id %s) is "
                "still referenced and was kept; it no longer has any certificate "
                "behaviour behind it.",
                certificate_category_id,
            )

    # storage_hint drops its 'certificate' value in this version; a row still
    # holding it would be an unrenderable selection.
    cr.execute(
        "UPDATE credential_category SET storage_hint = 'simple' "
        "WHERE storage_hint = 'certificate'",
    )

    # Name the rows rather than counting them, so an operator can tell
    # "nothing to do" from "move these by hand". This runs before any consumer
    # module's own migration — base_credential_manager is their dependency — so
    # the list is what holds material *now*, not what will still be stranded at
    # the end of the upgrade; hence "check whether", not "these are lost".
    if column_exists(cr, "credential_credential", "certificate_content_encrypted"):
        cr.execute(
            "SELECT id, name FROM credential_credential "
            "WHERE certificate_content_encrypted IS NOT NULL",
        )
        stranded = cr.fetchall()
        if stranded:
            _logger.warning(
                "base_credential_manager: %d credential(s) hold certificate material "
                "in columns this version makes inert: %s. The ciphertext stays in "
                "the database, but the ORM no longer reaches it. Modules migrating "
                "later in this same upgrade (e.g. remote_machines) move their own "
                "rows onto certificate.certificate and log that they did — check "
                "those lines, and recreate by hand only what none of them claimed.",
                len(stranded),
                ", ".join(f"{name!r} (id {cid})" for cid, name in stranded),
            )
