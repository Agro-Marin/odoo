from odoo.db import schema

MODEL = "account.payment"

RENAMES = (
    ("is_reconciled", "is_invoice_reconciled"),
    ("is_matched", "is_bank_matched"),
)


def _rewrite(expr, old, new):
    return rf"regexp_replace({expr}, '\y{old}\y', '{new}', 'g')"


def _matches(expr, old):
    return rf"{expr} ~ '\y{old}\y'"


def migrate(cr, version):
    if not version:
        return

    for old, new in RENAMES:
        if schema.column_exists(
            cr, "account_payment", old
        ) and not schema.column_exists(cr, "account_payment", new):
            cr.execute(
                f'ALTER TABLE "account_payment" RENAME COLUMN "{old}" TO "{new}"'
            )

        cr.execute(
            "UPDATE ir_model_fields SET name = %s WHERE model = %s AND name = %s",
            (new, MODEL, old),
        )
        cr.execute(
            "UPDATE ir_model_data SET name = %s WHERE model = 'ir.model.fields' AND name = %s",
            (f"field_account_payment__{new}", f"field_account_payment__{old}"),
        )

        cr.execute(
            f"""
            UPDATE ir_ui_view
               SET arch_db = {_rewrite("arch_db::text", old, new)}::jsonb
             WHERE {_matches("arch_db::text", old)}
               AND (model = %s
                    OR {_matches("arch_db::text", f"payment_id[.]{old}")}
                    OR {_matches("arch_db::text", f"origin_payment_id[.]{old}")})
            """,
            (MODEL,),
        )
        cr.execute(
            f"""
            UPDATE ir_filters
               SET domain = {_rewrite("domain", old, new)},
                   context = {_rewrite("context", old, new)},
                   sort = {_rewrite("sort", old, new)}
             WHERE model_id = %s
               AND ({_matches("domain", old)}
                    OR {_matches("context", old)}
                    OR {_matches("sort", old)})
            """,
            (MODEL,),
        )
        cr.execute(
            f"""
            UPDATE ir_act_window
               SET domain = {_rewrite("domain", old, new)},
                   context = {_rewrite("context", old, new)}
             WHERE res_model = %s
               AND ({_matches("domain", old)} OR {_matches("context", old)})
            """,
            (MODEL,),
        )
        cr.execute(
            f"""
            UPDATE ir_act_server a
               SET code = {_rewrite("a.code", old, new)}
              FROM ir_model m
             WHERE m.id = a.model_id
               AND m.model = %s
               AND {_matches("a.code", old)}
            """,
            (MODEL,),
        )
        cr.execute(
            """
            UPDATE ir_exports_line l
               SET name = %s
              FROM ir_exports e
             WHERE l.export_id = e.id AND e.resource = %s AND l.name = %s
            """,
            (new, MODEL, old),
        )
