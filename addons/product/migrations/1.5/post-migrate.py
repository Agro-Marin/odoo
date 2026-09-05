"""Post-migration: drop the column `is_in_selected_section_of_order` reserved.

The field is declared with a `search=` and nothing else: it exists so the
product catalog can put it in a domain, and no compute, default or write ever
assigns it. Declared without `store=False` it was nevertheless a real column,
which held NULL on every row of every database since it was introduced.

Marking the field `store=False` stops the ORM creating that column on a new
database but does not remove it from an existing one -- the ORM never drops
columns. This does, so the two agree.

Nothing reads the column: its only consumer is a domain, which the `search=`
method answers without touching storage.
"""

import logging
import typing

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

TABLE = "product_product"
COLUMN = "is_in_selected_section_of_order"


def migrate(cr: "Cursor", version: str | None) -> None:
    if not version:
        return

    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
         WHERE table_name = %s AND column_name = %s
        """,
        (TABLE, COLUMN),
    )
    if not cr.fetchone():
        return

    cr.execute(f'ALTER TABLE "{TABLE}" DROP COLUMN "{COLUMN}"')
    _logger.info("Dropped the unused column %s.%s", TABLE, COLUMN)
