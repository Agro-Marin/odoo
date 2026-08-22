from odoo.db.schema import column_exists

_TOKEN_PAIRS = (
    ("packaging_uom_qty", "quantity_packaging_uom"),
    ("action_open_reference", "action_view_reference"),
)


def _rewrite_sql(column_expr):
    for old, new in _TOKEN_PAIRS:
        column_expr = rf"regexp_replace({column_expr}, '\y{old}\y', '{new}', 'g')"
    return column_expr


_MATCH_ALTERNATION = "|".join(old for old, _ in _TOKEN_PAIRS)


def _match_sql(column_expr):
    return rf"{column_expr} ~ '\y({_MATCH_ALTERNATION})\y'"


def migrate(cr, version):
    if not version:
        return

    if column_exists(cr, "stock_move", "packaging_uom_qty") and not column_exists(
        cr, "stock_move", "quantity_packaging_uom"
    ):
        cr.execute(
            'ALTER TABLE "stock_move" '
            'RENAME COLUMN "packaging_uom_qty" TO "quantity_packaging_uom"'
        )

    cr.execute(
        f"""
        UPDATE ir_ui_view
           SET arch_db = {_rewrite_sql("arch_db::text")}::jsonb
         WHERE {_match_sql("arch_db::text")}
        """
    )

    cr.execute(
        f"""
        UPDATE ir_filters
           SET domain = {_rewrite_sql("domain")},
               context = {_rewrite_sql("context")},
               sort = {_rewrite_sql("sort")}
         WHERE model_id IN ('stock.move', 'stock.move.line')
           AND ({_match_sql("domain")} OR {_match_sql("context")} OR {_match_sql("sort")})
        """
    )

    cr.execute(
        """
        UPDATE ir_exports_line l
           SET name = 'quantity_packaging_uom'
          FROM ir_exports e
         WHERE l.export_id = e.id
           AND e.resource = 'stock.move'
           AND l.name = 'packaging_uom_qty'
        """
    )

    cr.execute(
        f"""
        UPDATE ir_act_server
           SET code = {_rewrite_sql("code")}
         WHERE {_match_sql("code")}
        """
    )
