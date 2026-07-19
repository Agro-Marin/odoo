r"""Pre-migration: normalize cross-category UoM data that strict conversion rejects.

Under the fork's strict UoM conversion (``uom.uom._compute_quantity`` raises a
``UserError`` when two units share no common reference), two legacy states left
by the pre-strict regime block operations at recompute time:

* ``stock.move.packaging_uom_id`` pinned (from a sale/purchase line) to a unit
  cross-category with the move's ``product_uom_id`` — e.g. a ``Units`` packaging
  on a move measured in ``kg``/``Liter``. The stored display value
  ``quantity_packaging_uom`` was computed under the old lenient regime as a blind
  ``qty * factor / factor`` (e.g. 120 -> 90000), so it is already meaningless.
* ``stock.warehouse.orderpoint.replenishment_uom_id`` (the reorder "Multiple")
  set cross-category with the product's ``uom_id``.

Rather than teach each compute to tolerate the bad data (which persists it, and
persists a silently wrong stored display value), this normalizes the data so the
strict computes are safe:

* moves: repoint ``packaging_uom_id`` to the move's own ``product_uom_id`` and
  reset ``quantity_packaging_uom`` to ``product_uom_qty`` — the exact value the
  strict compute yields when packaging == product UoM (identity conversion), and
  what ``_compute_packaging_uom_id`` produces for a move with no order-line pin.
* orderpoints: clear ``replenishment_uom_id`` (its help: "If it is not set, it is
  not rounded"), so replenishment is sized by the exact shortage in the product
  UoM — no meaningless cross-category multiple to round to.

Runs in ``pre-migrate`` so it lands after the 1.3/1.4 column renames
(``product_uom`` -> ``product_uom_id``, ``packaging_uom_qty`` ->
``quantity_packaging_uom``) but before the ORM recomputes the stored
``quantity_packaging_uom`` field — otherwise the strict recompute would raise on
the very records this fixes and abort the upgrade.

Cross-category is tested exactly as ``uom.uom._has_common_reference`` does for
stored records: the first ``parent_path`` segment (the reference-unit id) must
differ. The ``UPDATE``s are idempotent — their guards no longer match once a row
is normalized (packaging == product UoM shares the reference; a cleared multiple
is ``NULL``). Verified against the ``marin190_prod`` restore: 261 moves
(all done/cancelled, no open moves), 0 orderpoints.
"""

from odoo.tools.sql import column_exists


def migrate(cr, version):
    """Normalize cross-category packaging/replenishment UoMs to strict-safe values.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return  # fresh install: no legacy data to normalize

    # stock.move: cross-category packaging UoM -> the move's own product UoM,
    # and its stored display quantity -> the (identity) product quantity.
    if column_exists(cr, "stock_move", "packaging_uom_id"):
        cr.execute(
            r"""
            UPDATE stock_move sm
               SET packaging_uom_id     = sm.product_uom_id,
                   quantity_packaging_uom = sm.product_uom_qty
              FROM uom_uom pu, uom_uom ku
             WHERE pu.id = sm.product_uom_id
               AND ku.id = sm.packaging_uom_id
               AND sm.packaging_uom_id IS NOT NULL
               AND sm.packaging_uom_id <> sm.product_uom_id
               AND split_part(pu.parent_path, '/', 1)
                     <> split_part(ku.parent_path, '/', 1)
            """
        )

    # stock.warehouse.orderpoint: cross-category reorder multiple -> cleared
    # (no rounding), so replenishment is sized by the exact shortage.
    if column_exists(cr, "stock_warehouse_orderpoint", "replenishment_uom_id"):
        cr.execute(
            r"""
            UPDATE stock_warehouse_orderpoint op
               SET replenishment_uom_id = NULL
              FROM product_product pp
              JOIN product_template pt ON pt.id = pp.product_tmpl_id
              JOIN uom_uom pu ON pu.id = pt.uom_id,
                   uom_uom ru
             WHERE pp.id = op.product_id
               AND ru.id = op.replenishment_uom_id
               AND op.replenishment_uom_id IS NOT NULL
               AND split_part(pu.parent_path, '/', 1)
                     <> split_part(ru.parent_path, '/', 1)
            """
        )
