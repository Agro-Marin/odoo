r"""Pre-migration for the fork's earliest field renames, which shipped without one.

The initial fork commit (5b32001d5dd) renamed several ``stock`` fields; the
1.2-1.4 scripts only cover renames made *after* it. Three renamed fields are
stored computes — without a column rename the ORM would drop the old column and
trigger a full-table recompute of the new one at upgrade:

* ``stock.picking.scheduled_date``   -> ``date_planned``
* ``stock.move.delay_alert_date``    -> ``date_delay_alert``
* ``stock.move.reservation_date``    -> ``date_reservation``

The rest are non-stored, but their OLD names can survive in stored view arch
(studio / manually customized views), user-created ``ir.filters`` /
``ir.exports.line`` and server-action code, breaking ``-u`` at registry load
(see ``migrations/1.2/pre-migrate.py`` for the failure mode) or at runtime:

* ``stock.move.forecast_expected_date`` -> ``date_planned_forecast``
* ``stock.move.line.scheduled_date``    -> ``date_planned``
* ``stock.picking.packages_count``      -> ``count_packages``
* ``stock.lot.delivery_count``          -> ``count_transfer_outgoing``
* ``product.product`` / ``product.template``:
  ``virtual_available|incoming_qty|outgoing_qty|free_qty``
  -> ``qty_available_virtual|qty_incoming|qty_outgoing|qty_free``

All rewrites are whole-word (``\y``, Postgres word boundary — same approach as
1.3/1.4, protecting lookalikes such as ``virtual_available_at_date``,
``indirect_outgoing_qty`` or ``_search_free_qty``), in two tiers:

* GLOBAL — tokens whose old spelling survives on no model in the fork
  (``delay_alert_date``, ``reservation_date``, ``forecast_expected_date``,
  ``packages_count``): swept across all stored view arch, all filters, all
  export-line paths (including dotted paths like ``picking_id/packages_count``)
  and server-action code, exactly like 1.4.
* SCOPED — ambiguous tokens, rewritten only for artifacts anchored on the
  renamed model: ``scheduled_date`` is a live field on mail/event/... models
  and ``delivery_count`` on ``sale.order``; the product qty tokens are scoped
  for precision. Scoped tokens are deliberately NOT rewritten in
  ``ir_act_server.code``: an action anchored on ``stock.picking`` may
  legitimately manipulate another model's ``scheduled_date`` in its code, and
  the two cannot be told apart statically. A stale scoped token there fails at
  runtime with a clear ``AttributeError`` instead of corrupting user code.

``arch_db`` is jsonb (a per-language dict); field names are never translated
and never JSON keys, so the value-level regexp is safe (same rationale as 1.3).
Model filters use ``= ANY(%s)`` with a list — under this fork's psycopg3 a
tuple bound to ``IN %s`` collapses into a single parameter and errors out.
"""

from odoo.tools.sql import column_exists

# (table, old column, new column) — stored computes renamed by the fork.
_COLUMN_RENAMES = (
    ("stock_picking", "scheduled_date", "date_planned"),
    ("stock_move", "delay_alert_date", "date_delay_alert"),
    ("stock_move", "reservation_date", "date_reservation"),
)

# (old, new) — unambiguous fork-wide; safe for a global sweep.
_GLOBAL_PAIRS = (
    ("delay_alert_date", "date_delay_alert"),
    ("reservation_date", "date_reservation"),
    ("forecast_expected_date", "date_planned_forecast"),
    ("packages_count", "count_packages"),
)

# (models, (old, new) pairs) — ambiguous tokens, rewritten per anchor model.
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
    """Build a nested ``regexp_replace`` SQL expression rewriting every token
    pair, whole-word, in a single pass over ``column_expr``.

    :param str column_expr: SQL expression (column or cast) to rewrite
    :param pairs: iterable of ``(old, new)`` token pairs
    :return: SQL expression with all renames applied
    :rtype: str
    """
    for old, new in pairs:
        column_expr = rf"regexp_replace({column_expr}, '\y{old}\y', '{new}', 'g')"
    return column_expr


def _match_sql(column_expr, pairs):
    """Build the ``WHERE`` guard matching any old token in one alternation
    regexp (one per-row regex evaluation instead of one per token).

    :param str column_expr: SQL expression (column or cast) to test
    :param pairs: iterable of ``(old, new)`` token pairs
    :return: SQL boolean expression
    :rtype: str
    """
    alternation = "|".join(old for old, _ in pairs)
    return rf"{column_expr} ~ '\y({alternation})\y'"


def migrate(cr, version):
    """Rename the stored columns and refresh stored references to old names.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return  # fresh install: the ORM creates the new columns directly

    for table, old, new in _COLUMN_RENAMES:
        if column_exists(cr, table, old) and not column_exists(cr, table, new):
            cr.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"')

    # Stored view arch and user filters: one global pass, then one pass per
    # scoped model group. ``None`` as the model list means "no model filter".
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

    # Export lines. Global tokens: regexp on the whole path, so dotted paths
    # from other models (``picking_id/packages_count``) are covered too.
    cr.execute(
        f"""
        UPDATE ir_exports_line
           SET name = {_rewrite_sql("name", _GLOBAL_PAIRS)}
         WHERE {_match_sql("name", _GLOBAL_PAIRS)}
        """
    )
    # Scoped tokens: exact field-name match per anchor resource (the 1.3/1.4
    # approach) — a dotted ``scheduled_date`` under another resource cannot be
    # attributed to stock.picking reliably.
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

    # Server actions: global (unambiguous) tokens only — see module docstring.
    cr.execute(
        f"""
        UPDATE ir_act_server
           SET code = {_rewrite_sql("code", _GLOBAL_PAIRS)}
         WHERE {_match_sql("code", _GLOBAL_PAIRS)}
        """
    )
