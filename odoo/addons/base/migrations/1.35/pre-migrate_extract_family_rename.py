r"""Pre-migration: the ``document_extract`` module family becomes ``extract``.

The ``document_`` prefix means "bridges the ``document`` app" for every other
module wearing it, and none of these eleven depends on that app. The rename
lives in ``base`` because a renamed module is a new module to the loader: its
own ``migrations/`` never runs while ``ir_module_module`` still carries the old
row. ``base`` is upgraded before every other module.

One abstract model moves with the modules, ``mixin.document.extract`` to
``mixin.extract``. It has no table, so what moves is its ``ir_model`` row, its
fields' rows and the xml ids the ORM derives from the name. The job channel is
matched by name at dispatch, so its row is renamed rather than left for the
update to recreate under a new xml id with queued jobs still pointing at the old.
Every statement is idempotent.
"""

from odoo.db import schema
from odoo.tools import SQL

MODULES = {
    "document_extract": "extract",
    "document_extract_account": "extract_account",
    "document_extract_account_bank_statement": "extract_account_bank_statement",
    "document_extract_account_purchase": "extract_account_purchase",
    "document_extract_ai": "extract_ai",
    "document_extract_barcode": "extract_barcode",
    "document_extract_hr_expense": "extract_hr_expense",
    "document_extract_hr_expense_predict": "extract_hr_expense_predict",
    "document_extract_hr_recruitment": "extract_hr_recruitment",
    "document_extract_hr_recruitment_skills": "extract_hr_recruitment_skills",
    "document_extract_ocr": "extract_ocr",
}

MODELS = {"mixin.document.extract": "mixin.extract"}

JOB_CHANNELS = {"document_extract": "extract"}


def _rename_modules(cr):
    for old, new in MODULES.items():
        cr.execute(
            """
            DELETE FROM ir_model_data dissolved USING ir_model_data surviving
                  WHERE dissolved.module = %s AND surviving.module = %s
                    AND surviving.name = dissolved.name
            """,
            [old, new],
        )
        cr.execute("UPDATE ir_model_data SET module = %s WHERE module = %s", [new, old])
        cr.execute("UPDATE ir_module_module SET name = %s WHERE name = %s", [new, old])
        for table in ("ir_module_module_dependency", "ir_module_module_exclusion"):
            if schema.table_exists(cr, table):
                cr.execute(
                    SQL(
                        "UPDATE %s SET name = %s WHERE name = %s",
                        SQL.identifier(table),
                        new,
                        old,
                    )
                )
        cr.execute(
            """
            UPDATE ir_model_data SET name = %s
             WHERE module = 'base' AND model = 'ir.module.module' AND name = %s
            """,
            [f"module_{new}", f"module_{old}"],
        )
    cr.execute(
        "UPDATE ir_module_module SET data_file_checksums = NULL WHERE name = ANY(%s)",
        [list(MODULES.values())],
    )


def _rename_file_xml_ids(cr):
    """Ids declared in data files that carried the module's name in their own."""
    cr.execute(
        """
        UPDATE ir_model_data
           SET name = replace(name, 'document_extract', 'extract')
         WHERE module = ANY(%s)
           AND name LIKE %s
           AND name NOT LIKE 'model\\_%%'
           AND name NOT LIKE 'field\\_%%'
        """,
        [list(MODULES.values()), "%document\\_extract%"],
    )


def _rename_models(cr):
    for old, new in MODELS.items():
        old_table, new_table = old.replace(".", "_"), new.replace(".", "_")
        for table in ("ir_model", "ir_model_fields", "ir_model_fields_selection"):
            if schema.table_exists(cr, table) and schema.column_exists(
                cr, table, "model"
            ):
                cr.execute(
                    SQL(
                        "UPDATE %s SET model = %s WHERE model = %s",
                        SQL.identifier(table),
                        new,
                        old,
                    )
                )
        cr.execute("UPDATE ir_model_data SET model = %s WHERE model = %s", [new, old])
        cr.execute(
            "UPDATE ir_model_data SET name = %s WHERE model = 'ir.model' AND name = %s",
            [f"model_{new_table}", f"model_{old_table}"],
        )
        cr.execute(
            """
            UPDATE ir_model_data SET name = %s || substring(name from %s)
             WHERE model = 'ir.model.fields' AND name LIKE %s
            """,
            [
                f"field_{new_table}",
                len(f"field_{old_table}") + 1,
                f"field_{old_table}\\_\\_%",
            ],
        )


def _rename_job_channels(cr):
    if not schema.table_exists(cr, "ir_job_channel"):
        return
    for old, new in JOB_CHANNELS.items():
        cr.execute(
            """
            UPDATE ir_job_channel SET name = %s WHERE name = %s
               AND NOT EXISTS (SELECT 1 FROM ir_job_channel WHERE name = %s)
            """,
            [new, old, new],
        )
        if schema.table_exists(cr, "ir_job") and schema.column_exists(
            cr, "ir_job", "channel"
        ):
            cr.execute("UPDATE ir_job SET channel = %s WHERE channel = %s", [new, old])


def migrate(cr, version):
    if not version:
        return
    _rename_modules(cr)
    _rename_file_xml_ids(cr)
    _rename_models(cr)
    _rename_job_channels(cr)
