OLD = "is_favorite"
NEW = "is_user_favorite"
MODEL = "stock.picking.type"

OLD_RELATION = "picking_type_favorite_user_rel"
NEW_RELATION = "res_users_stock_picking_type_rel"
COLUMNS = (("picking_type_id", "stock_picking_type_id"), ("user_id", "res_users_id"))


def _rewrite(expr):
    return rf"regexp_replace({expr}, '\y{OLD}\y', '{NEW}', 'g')"


def _matches(expr):
    return rf"{expr} ~ '\y{OLD}\y'"


def _rename_relation(cr):
    cr.execute("SELECT to_regclass(%s)", (OLD_RELATION,))
    if not cr.fetchone()[0]:
        return
    cr.execute(f'ALTER TABLE "{OLD_RELATION}" RENAME TO "{NEW_RELATION}"')
    for old_column, new_column in COLUMNS:
        cr.execute(
            f'ALTER TABLE "{NEW_RELATION}" RENAME COLUMN "{old_column}"'
            f' TO "{new_column}"'
        )


def migrate(cr, version):
    if not version:
        return

    _rename_relation(cr)

    cr.execute(
        f"""
        UPDATE ir_ui_view
           SET arch_db = {_rewrite("arch_db::text")}::jsonb
         WHERE {_matches("arch_db::text")}
           AND model = %s
        """,
        (MODEL,),
    )
    cr.execute(
        f"""
        UPDATE ir_filters
           SET domain = {_rewrite("domain")},
               context = {_rewrite("context")},
               sort = {_rewrite("sort")}
         WHERE ({_matches("domain")}
                OR {_matches("context")}
                OR {_matches("sort")})
           AND model_id = %s
        """,
        (MODEL,),
    )
    cr.execute(
        f"""
        UPDATE ir_act_window
           SET domain = {_rewrite("domain")},
               context = {_rewrite("context")}
         WHERE ({_matches("domain")} OR {_matches("context")})
           AND res_model = %s
        """,
        (MODEL,),
    )
