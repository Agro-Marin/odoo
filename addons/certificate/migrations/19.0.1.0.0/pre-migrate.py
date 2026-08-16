from odoo.db import schema
from odoo.tools import SQL

_COLUMN_RENAMES = (
    ("certificate_key", "password", "password_plain"),
    ("certificate_certificate", "pkcs12_password", "pkcs12_password_plain"),
)

_ATTACHMENT_MODELS = ("certificate.key", "certificate.certificate")


def migrate(cr, version):
    if not version:
        return

    for table, old, new in _COLUMN_RENAMES:
        if not schema.table_exists(cr, table):
            continue
        if not schema.column_exists(cr, table, old):
            continue
        if schema.column_exists(cr, table, new):
            continue
        cr.execute(
            SQL(
                "ALTER TABLE %s RENAME COLUMN %s TO %s",
                SQL.identifier(table),
                SQL.identifier(old),
                SQL.identifier(new),
            )
        )

    cr.execute(
        """
        UPDATE ir_attachment
           SET res_field = 'content_plain'
         WHERE res_model = ANY(%s)
           AND res_field = 'content'
        """,
        [list(_ATTACHMENT_MODELS)],
    )

    cr.execute(
        """
        DELETE FROM ir_model_data dissolved
              USING ir_model_data surviving
              WHERE dissolved.module = 'certificate_encryption'
                AND surviving.module = 'certificate'
                AND surviving.name = dissolved.name
        """
    )
    cr.execute(
        """
        UPDATE ir_model_data
           SET module = 'certificate'
         WHERE module = 'certificate_encryption'
        """
    )
    cr.execute(
        """
        UPDATE ir_module_module
           SET state = 'uninstalled'
         WHERE name = 'certificate_encryption'
           AND state NOT IN ('uninstalled', 'uninstallable')
        """
    )
