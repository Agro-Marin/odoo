"""Drop ``product.document`` (1.2).

Contract step of the product-document dissolution. 1.1 backfilled every
``product.document`` into a ``documents.document`` over the same attachment and
copied the discriminator columns across; this drops what is left.

Ordering matters and is why the drop lives here rather than in `product`:
`documents_product` is the module that owns both halves of the move, so 1.1 is
guaranteed to have run against this database before 1.2 does. Re-running the
backfill first is deliberate belt-and-braces -- a database upgraded straight from
a version predating 1.1 would otherwise lose rows.

Six objects in this database still carry a foreign key to the table -- the
``mrp.eco`` image column and five relation tables from modules whose own m2m has
since moved to ``documents.document``. Nothing in the tree declares
``product.document`` any more, so those are leftover schema: Postgres still
refuses the drop, and Odoo never sweeps an orphaned relation table or a
retargeted column's old constraint on its own. They are dropped by name here,
one statement each, rather than with ``DROP TABLE ... CASCADE`` -- the columns
and relation tables themselves must survive, and each referencing module
recreates its own constraint against the new target at its next ``_auto_init``.

The attachments are NOT touched. ``product.document`` cascade-deleted its
attachment on unlink, but every one of these attachments is now carried by a
``documents.document``, so dropping the table must leave them alone. Deleting the
``ir_model`` row is what removes the model's fields, constraints and ACLs, and
the ORM would otherwise resurrect the table on the next registry load.
"""

import logging

from odoo.db.schema import table_exists

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not table_exists(cr, "product_document"):
        return

    _rerun_backfill(cr)

    cr.execute("SELECT count(*) FROM product_document")
    remaining = cr.fetchone()[0]

    # The satellites -- ACL rows and the multi-company rule -- cascade when the
    # `ir_model` row goes, which leaves their xmlids pointing at nothing.
    # `_process_end` cannot sweep those afterwards: it removes a record and then
    # its xmlid, and by then the record is already gone. So drop the xmlids while
    # the ids are still resolvable.
    for model, table in (("ir.rule", "ir_rule"), ("ir.model.access", "ir_model_access")):
        cr.execute(
            f"""
            DELETE FROM ir_model_data
                  WHERE model = %s
                    AND res_id IN (
                            SELECT s.id
                              FROM {table} s
                              JOIN ir_model m ON m.id = s.model_id
                             WHERE m.model = 'product.document'
                        )
            """,
            [model],
        )
    cr.execute(
        """
        DELETE FROM ir_model_data
              WHERE model = 'ir.model.fields'
                AND res_id IN (
                        SELECT f.id
                          FROM ir_model_fields f
                          JOIN ir_model m ON m.id = f.model_id
                         WHERE m.model = 'product.document'
                    )
        """
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
              WHERE model = 'ir.model'
                AND res_id IN (SELECT id FROM ir_model WHERE model = 'product.document')
        """
    )
    # The ir_model_fields, ir_model_access and ir_rule ROWS cascade from here;
    # their xmlids were dropped above, while their ids still resolved.
    cr.execute("DELETE FROM ir_model WHERE model = 'product.document'")
    _drop_dependent_constraints(cr)
    cr.execute("DROP TABLE product_document")

    _logger.info(
        "product.document dropped; %s row(s) had already been carried over to "
        "documents.document",
        remaining,
    )


def _rerun_backfill(cr):
    """Idempotent, so running 1.1's pass again only fills gaps."""
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).parents[1] / "1.1" / "post-migrate.py"
    spec = importlib.util.spec_from_file_location("_backfill_1_1", path)
    backfill = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backfill)
    backfill.migrate(cr, "1.1")


def _drop_dependent_constraints(cr):
    """Release every foreign key still pointing at ``product_document``."""
    cr.execute(
        """
        SELECT c.conrelid::regclass::text, c.conname
          FROM pg_constraint c
         WHERE c.confrelid = 'product_document'::regclass
           AND c.contype = 'f'
        """
    )
    for table, constraint in cr.fetchall():
        cr.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{constraint}"')
        _logger.info("Dropped stale FK %s on %s", constraint, table)
