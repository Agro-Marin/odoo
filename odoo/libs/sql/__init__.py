"""SQL string utilities and the composable ``SQL`` query wrapper.

Framework-free (no ``odoo`` runtime imports): the ``SQL`` builder, the pure
string helpers, and the trigram search-pattern transforms. Cursor-executing
schema DDL lives in :mod:`odoo.db.schema`, not here (ADR-0004).
"""

from .builder import SQL
from .trigram import (
    pattern_to_translated_trigram_pattern,
    value_to_translated_trigram_pattern,
)
from .utils import (
    escape_psql,
    make_identifier,
    make_index_name,
    pg_varchar,
    reverse_order,
)

__all__ = [
    "SQL",
    "escape_psql",
    "make_identifier",
    "make_index_name",
    "pattern_to_translated_trigram_pattern",
    "pg_varchar",
    "reverse_order",
    "value_to_translated_trigram_pattern",
]
