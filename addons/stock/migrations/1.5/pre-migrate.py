from odoo.db.schema import column_exists

_COLUMN_RENAMES = (
    ("stock_picking", "scheduled_date", "date_planned"),
    ("stock_move", "delay_alert_date", "date_delay_alert"),
    ("stock_move", "reservation_date", "date_reservation"),
)

_GLOBAL_PAIRS = (
    ("delay_alert_date", "date_delay_alert"),
    ("reservation_date", "date_reservation"),
    ("forecast_expected_date", "date_planned_forecast"),
    ("packages_count", "count_packages"),
)

_SCOPED_GROUPS = (
    (
        ["stock.picking", "stock.move.line"],
        (("scheduled_date", "date_planned"),),
    ),
    (
        ["stock.lot"],
        (("delivery_count", "count_transfer_outgoing"),),
    ),
    (
        ["product.product", "product.template"],
        (
            ("virtual_available", "qty_available_virtual"),
            ("incoming_qty", "qty_incoming"),
            ("outgoing_qty", "qty_outgoing"),
            ("free_qty", "qty_free"),
        ),
    ),
)


def _rewrite_sql(column_expr, pairs):
    for old, new in pairs:
        column_expr = rf"regexp_replace({column_expr}, '\y{old}\y', '{new}', 'g')"
    return column_expr


def _match_sql(column_expr, pairs):
    alternation = "|".join(old for old, _ in pairs)
    return rf"{column_expr} ~ '\y({alternation})\y'"


def migrate(cr, version):
    if not version:
        return

    for table, old, new in _COLUMN_RENAMES:
        if column_exists(cr, table, old) and not column_exists(cr, table, new):
            cr.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"')

    for models, pairs in ((None, _GLOBAL_PAIRS), *_SCOPED_GROUPS):
        view_filter = " AND model = ANY(%s)" if models else ""
        filter_filter = " AND model_id = ANY(%s)" if models else ""
        params = (models,) if models else None
        cr.execute(
            f"""
            UPDATE ir_ui_view
               SET arch_db = {_rewrite_sql("arch_db::text", pairs)}::jsonb
             WHERE {_match_sql("arch_db::text", pairs)}{view_filter}
            """,
            params,
        )
        cr.execute(
            f"""
            UPDATE ir_filters
               SET domain = {_rewrite_sql("domain", pairs)},
                   context = {_rewrite_sql("context", pairs)},
                   sort = {_rewrite_sql("sort", pairs)}
             WHERE ({_match_sql("domain", pairs)}
                    OR {_match_sql("context", pairs)}
                    OR {_match_sql("sort", pairs)}){filter_filter}
            """,
            params,
        )

    cr.execute(
        f"""
        UPDATE ir_exports_line
           SET name = {_rewrite_sql("name", _GLOBAL_PAIRS)}
         WHERE {_match_sql("name", _GLOBAL_PAIRS)}
        """
    )
    for models, pairs in _SCOPED_GROUPS:
        for old, new in pairs:
            cr.execute(
                """
                UPDATE ir_exports_line l
                   SET name = %s
                  FROM ir_exports e
                 WHERE l.export_id = e.id
                   AND e.resource = ANY(%s)
                   AND l.name = %s
                """,
                (new, models, old),
            )

    cr.execute(
        f"""
        UPDATE ir_act_server
           SET code = {_rewrite_sql("code", _GLOBAL_PAIRS)}
         WHERE {_match_sql("code", _GLOBAL_PAIRS)}
        """
    )
