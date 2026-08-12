r"""Pre-migration: make existing ``stock.location`` rows satisfy two tightened constraints.

Both constraints below are created by the ORM *after* this script runs, and a
constraint whose table already violates it aborts the upgrade with a bare
PostgreSQL error naming neither the offending rows nor the fix. So the data is
normalized here first.

* ``_inventory_freq_bounded`` replaces ``_inventory_freq_nonneg``:
  ``cyclic_inventory_frequency`` is now bounded above as well
  (``MAX_CYCLIC_INVENTORY_DAYS`` = 36500 days ≈ a century). The old constraint
  admitted any positive integer, and a large one overflowed
  ``_compute_next_inventory_date`` — turning every later *read* of
  ``next_inventory_date``, and every upgrade that recomputes it, into a
  ``UserError``. Rows above the bound are clamped to it: the schedule they
  encoded was already unreachable, and clamping keeps the location on a cyclic
  count rather than silently dropping it to "never".

* the ``_barcode_company_uniq`` CONSTRAINT becomes a partial
  ``_barcode_company_unique_idx`` UNIQUE INDEX over
  ``(barcode, COALESCE(company_id, 0))``: ``company_id`` is nullable by design
  ("shared between companies"), and under PostgreSQL's default NULLS DISTINCT the
  old index never bound two *shared* locations, so duplicate barcodes could
  accumulate there. Barcode is in ``_rec_names_search`` and is what barcode
  scanning resolves on, so a duplicate makes a scan pick arbitrarily. Duplicates
  among shared locations are resolved by keeping the barcode on the lowest id and
  clearing it on the rest — the conservative direction, since clearing a barcode
  degrades scanning while rewriting one would silently redirect it.

  The old constraint is dropped here rather than left to the registry: a UNIQUE
  constraint owns its backing index, so PostgreSQL refuses to drop that index
  while the constraint stands.

Both statements are idempotent: their guards no longer match once a row is
normalized.
"""

from odoo.db.schema import column_exists

MAX_CYCLIC_INVENTORY_DAYS = 36500


def migrate(cr, version):
    """Clamp out-of-range inventory frequencies and de-duplicate shared barcodes.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    if column_exists(cr, "stock_location", "cyclic_inventory_frequency"):
        cr.execute(
            """
            UPDATE stock_location
               SET cyclic_inventory_frequency = %s
             WHERE cyclic_inventory_frequency > %s
            """,
            (MAX_CYCLIC_INVENTORY_DAYS, MAX_CYCLIC_INVENTORY_DAYS),
        )

    if column_exists(cr, "stock_location", "barcode"):
        # Only company-less rows can hold duplicates today: the pre-existing index
        # already bound every row that names a company.
        cr.execute(
            """
            UPDATE stock_location
               SET barcode = NULL
             WHERE company_id IS NULL
               AND barcode IS NOT NULL
               AND id NOT IN (
                     SELECT min(id)
                       FROM stock_location
                      WHERE company_id IS NULL
                        AND barcode IS NOT NULL
                   GROUP BY barcode
                   )
            """
        )
        cr.execute(
            """
            ALTER TABLE stock_location
            DROP CONSTRAINT IF EXISTS stock_location_barcode_company_uniq
            """
        )
        cr.execute(
            """
            DELETE FROM ir_model_constraint
             WHERE name = 'stock_location_barcode_company_uniq'
            """
        )
