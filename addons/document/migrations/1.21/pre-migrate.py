from odoo.db.schema import column_exists


def migrate(cr, version):
    if not version:
        return
    # the token becomes an access.link row in the post-migrate; until then the
    # column keeps it, and documents the upgrade creates carry none
    if column_exists(cr, "document_document", "document_token"):
        cr.execute(
            "ALTER TABLE document_document ALTER COLUMN document_token DROP NOT NULL"
        )
