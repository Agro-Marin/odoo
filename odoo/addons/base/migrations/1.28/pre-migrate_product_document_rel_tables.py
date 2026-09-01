r"""Pre-migration: retire the relation tables left over by the product.document drop.

``sale_pdf_quote_builder.product_document_ids`` keeps its relation table name,
``sale_order_line_product_document_rel``, but its comodel is now
``documents.document``. The ORM therefore wants a ``documents_document_id``
column in a table that already exists carrying ``product_document_id`` --
and ``_auto_init`` adds a missing *constraint* to an existing relation table
without adding the missing *column*, so the upgrade dies on `column
"documents_document_id" referenced in foreign key constraint does not exist`.

Dropping the table is what lets ``_auto_init`` rebuild it in the new shape.

That is only lossless while the table is empty, which is the case here for
every table this touches -- the links this database holds are on
``product_document_product_msds_rel`` and
``product_document_product_technical_sheet_rel`` (51 rows each), and neither is
named by any model in the tree any more, so nothing reads or rebuilds them and
they are left untouched rather than dropped.

A populated table is a different problem and is deliberately left alone with a
warning: the only mapping from a ``product.document`` to the
``documents.document`` that replaced it is the shared ``attachment_id``, and
``documents_product``'s 1.2 drops ``product_document`` -- so a remap has to
happen there, before the drop, not here.
"""

import logging
import typing

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

# Relation tables the new code re-declares against `documents.document`.
REBUILT_RELATIONS = ("sale_order_line_product_document_rel",)


def migrate(cr: "Cursor", version: str | None) -> None:
    if not version:
        return

    for table in REBUILT_RELATIONS:
        cr.execute("SELECT to_regclass(%s)", (f"public.{table}",))
        if not cr.fetchone()[0]:
            continue
        cr.execute(
            """
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = %s
               AND column_name = 'product_document_id'
            """,
            (table,),
        )
        if not cr.fetchone():
            continue  # already rebuilt

        cr.execute(f'SELECT count(*) FROM "{table}"')
        rows = cr.fetchone()[0]
        if rows:
            _logger.warning(
                "%s still holds %d row(s) pointing at the dropped "
                "product.document; leaving it in place -- those links need "
                "remapping through ir_attachment before product_document goes",
                table,
                rows,
            )
            continue

        cr.execute(f'DROP TABLE "{table}"')
        _logger.info("Dropped empty %s so _auto_init rebuilds it", table)
