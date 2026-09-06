from odoo.db.schema import table_exists

EXPIRING_SOON_DAYS = 30


def backfill_expiration_state(cr):
    if not table_exists(cr, "document_type"):
        return
    cr.execute(
        """
        UPDATE document_document d
        SET expiration_state = CASE
            WHEN dt.has_expiration IS NOT TRUE THEN NULL
            WHEN d.date_expiration IS NULL THEN 'missing'
            WHEN d.date_expiration < CURRENT_DATE THEN 'expired'
            WHEN d.date_expiration <= CURRENT_DATE + %s THEN 'expiring_soon'
            ELSE 'valid'
        END
        FROM document_document src
        LEFT JOIN document_type dt ON dt.id = src.document_type_id
        WHERE src.id = d.id
        """,
        [EXPIRING_SOON_DAYS],
    )


def migrate(cr, version):
    if not version:
        return
    backfill_expiration_state(cr)
