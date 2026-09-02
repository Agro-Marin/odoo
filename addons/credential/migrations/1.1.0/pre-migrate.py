import logging

from odoo.db.schema import column_exists

_logger = logging.getLogger(__name__)

_MODULE = "credential"


def _xml_id_res_id(cr, name):
    cr.execute(
        "SELECT res_id FROM ir_model_data WHERE module = %s AND name = %s",
        (_MODULE, name),
    )
    row = cr.fetchone()
    return row[0] if row else None


def migrate(cr, version):
    certificate_category_id = _xml_id_res_id(cr, "credential_category_certificate")
    fallback_id = _xml_id_res_id(cr, "credential_category_custom")

    if certificate_category_id and fallback_id:
        cr.execute(
            "UPDATE credential_credential SET category_id = %s WHERE category_id = %s",
            (fallback_id, certificate_category_id),
        )
        if cr.rowcount:
            _logger.info(
                "credential: moved %d credential(s) off the retired "
                "'certificate' category onto 'custom'",
                cr.rowcount,
            )

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
                "credential: removed the retired 'certificate' category",
            )
        else:
            _logger.warning(
                "credential: the 'certificate' category (id %s) is "
                "still referenced and was kept; it no longer has any certificate "
                "behaviour behind it.",
                certificate_category_id,
            )

    cr.execute(
        "UPDATE credential_category SET storage_hint = 'simple' "
        "WHERE storage_hint = 'certificate'",
    )

    if column_exists(cr, "credential_credential", "certificate_content_encrypted"):
        cr.execute(
            "SELECT id, name FROM credential_credential "
            "WHERE certificate_content_encrypted IS NOT NULL",
        )
        stranded = cr.fetchall()
        if stranded:
            _logger.warning(
                "credential: %d credential(s) hold certificate material "
                "in columns this version makes inert: %s. The ciphertext stays in "
                "the database, but the ORM no longer reaches it. Modules migrating "
                "later in this same upgrade (e.g. remote_machines) move their own "
                "rows onto certificate.certificate and log that they did — check "
                "those lines, and recreate by hand only what none of them claimed.",
                len(stranded),
                ", ".join(f"{name!r} (id {cid})" for cid, name in stranded),
            )
