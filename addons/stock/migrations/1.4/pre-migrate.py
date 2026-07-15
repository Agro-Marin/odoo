r"""Pre-migration for two field/method renames that shipped without one:
``stock.move.packaging_uom_qty`` (stored, ``store=True``) -> ``quantity_packaging_uom``,
and the method ``stock.move(.line).action_open_reference`` -> ``action_view_reference``
(invoked from view arch via ``action="..." type="object"``, so a stale stored
reference only breaks at runtime with an ``AttributeError``, not at install
time).

Both whole-word rewrites below share the ``\y`` (Postgres word boundary)
approach used by ``migrations/1.3/pre-migrate.py``: it keeps lookalikes such
as ``product_packaging_uom_qty`` (enterprise) untouched, since ``\y`` does not
match on a ``_`` boundary.

Unlike 1.3, this script also sweeps ``ir_act_server.code`` (1.3 only ever
touched ``ir_ui_view``/``ir_filters``/``ir_exports_line``). Only these two
unambiguous token pairs are rewritten here — the unrelated
``product_uom -> product_uom_id`` one-offs in ``ir_act_server`` are a
deploy-time SQL script, not a migration: a bare whole-word sweep of
``product_uom`` across all of ``ir_act_server`` would be unsafe (ambiguous
token in arbitrary user code), unlike the two renames here.
"""

from odoo.tools.sql import column_exists

_TOKEN_PAIRS = (
    ("packaging_uom_qty", "quantity_packaging_uom"),
    ("action_open_reference", "action_view_reference"),
)


def _rewrite_sql(column_expr):
    """Build a nested ``regexp_replace`` SQL expression rewriting both token
    pairs, whole-word, in a single pass over ``column_expr``.

    :param str column_expr: SQL expression (column or cast) to rewrite
    :return: SQL expression with both renames applied
    :rtype: str
    """
    for old, new in _TOKEN_PAIRS:
        column_expr = rf"regexp_replace({column_expr}, '\y{old}\y', '{new}', 'g')"
    return column_expr


_MATCH_ALTERNATION = "|".join(old for old, _ in _TOKEN_PAIRS)


def _match_sql(column_expr):
    """Build the ``WHERE`` guard matching either old token, in a single
    alternation regexp rather than one ``~`` test per token — halves (or, for
    the 3-column ``ir_filters`` guard, thirds) the per-row regex evaluations
    and, for ``ir_ui_view``, the number of times the jsonb ``arch_db`` column
    is cast to text.

    :param str column_expr: SQL expression (column or cast) to test
    :return: SQL boolean expression
    :rtype: str
    """
    return rf"{column_expr} ~ '\y({_MATCH_ALTERNATION})\y'"


def migrate(cr, version):
    """Rename the column and refresh stored references to both old names.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return  # fresh install: the ORM creates quantity_packaging_uom directly

    if column_exists(cr, "stock_move", "packaging_uom_qty") and not column_exists(
        cr, "stock_move", "quantity_packaging_uom"
    ):
        cr.execute(
            'ALTER TABLE "stock_move" '
            'RENAME COLUMN "packaging_uom_qty" TO "quantity_packaging_uom"'
        )

    # Whole-word rewrite in stored view arch (jsonb) for both renamed tokens.
    cr.execute(
        f"""
        UPDATE ir_ui_view
           SET arch_db = {_rewrite_sql("arch_db::text")}::jsonb
         WHERE {_match_sql("arch_db::text")}
        """
    )

    # User-created filters referencing the old field name or the old method.
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

    # Exported field name — export lines only ever reference field paths, so
    # only the field-rename pair applies here (exact match, like 1.3).
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

    # Server actions (ir.actions.server) whose Python code references either
    # old token — closes the A9 gap left open by the 1.3 migration.
    cr.execute(
        f"""
        UPDATE ir_act_server
           SET code = {_rewrite_sql("code")}
         WHERE {_match_sql("code")}
        """
    )
