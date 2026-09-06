import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

# source_ref and note are resolved from source_key at read time now, and the
# ceiling is a property of the catalog rather than a column on every partner.
# The ORM leaves a column it no longer knows in place; drop them so the schema
# says the same thing the model does.
_DROPPED = (
    ("partner_score_line", "source_ref"),
    ("partner_score_line", "note"),
    ("res_partner", "score_max_possible"),
)


def migrate(cr, version):
    for table, column in _DROPPED:
        if schema.column_exists(cr, table, column):
            cr.execute(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')
            _logger.info("partner_scoring 19.0.1.5.0: dropped %s.%s", table, column)
