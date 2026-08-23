from odoo.db import schema

MODEL = "account.journal"

RENAMES = (
    ("account_control_ids", "allowed_account_ids", "account_journal_account_account_control_rel", "account_journal_allowed_account_rel"),
    ("user_can_access_ids", "allowed_user_ids", "account_journal_res_users_can_access_rel", "account_journal_allowed_user_rel"),
)


def _rewrite(expr, old, new):
    return rf"regexp_replace({expr}, '\y{old}\y', '{new}', 'g')"


def _matches(expr, old):
    return rf"{expr} ~ '\y{old}\y'"


def migrate(cr, version):
    if not version:
        return

    for old, new, old_table, new_table in RENAMES:
        if schema.table_exists(cr, old_table) and not schema.table_exists(cr, new_table):
            cr.execute(f'ALTER TABLE "{old_table}" RENAME TO "{new_table}"')

        cr.execute(
            "UPDATE ir_model_data SET name = %s WHERE model = 'ir.model.fields' AND name = %s",
            (f"field_account_journal__{new}", f"field_account_journal__{old}"),
        )
        cr.execute(
            "UPDATE ir_model_fields SET name = %s WHERE model = %s AND name = %s",
            (new, MODEL, old),
        )

        # user_can_access_ids is also a stock.picking.type field, so a blanket
        # rewrite would corrupt that model's views. Stay inside account.journal,
        # and take the dotted form wherever a move-side record walks through it.
        cr.execute(
            f"""
            UPDATE ir_ui_view
               SET arch_db = {_rewrite("arch_db::text", old, new)}::jsonb
             WHERE {_matches("arch_db::text", old)}
               AND (model = %s OR {_matches("arch_db::text", f"journal_id[.]{old}")})
            """,
            (MODEL,),
        )
        cr.execute(
            f"""
            UPDATE ir_filters
               SET domain = {_rewrite("domain", old, new)},
                   context = {_rewrite("context", old, new)},
                   sort = {_rewrite("sort", old, new)}
             WHERE ({_matches("domain", old)}
                    OR {_matches("context", old)}
                    OR {_matches("sort", old)})
               AND (model_id = %s OR {_matches("domain", f"journal_id[.]{old}")})
            """,
            (MODEL,),
        )
        cr.execute(
            f"""
            UPDATE ir_act_window
               SET domain = {_rewrite("domain", old, new)},
                   context = {_rewrite("context", old, new)}
             WHERE ({_matches("domain", old)} OR {_matches("context", old)})
               AND (res_model = %s OR {_matches("domain", f"journal_id[.]{old}")})
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
