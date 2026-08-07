"""``create_index`` must accept a literal ``%`` in expressions and WHERE clauses.

``expressions`` and ``where`` are raw SQL fragments, but they were handed
straight to ``SQL(fragment)``, whose no-argument branch runs ``code % ()`` as an
arity check.  A fragment holding a literal ``%`` -- e.g. the partial index
``where="name LIKE 'a%'"`` -- therefore raised ``TypeError: not enough arguments
for format string`` before any SQL was emitted, so the index was silently never
created and module installation failed.

``add_index`` already escaped ``%`` for its ``str`` definition; ``create_index``,
which builds a definition and delegates to it, did not.  psycopg collapses
``%%`` back to ``%`` even when the parameter tuple is empty (verified against
PostgreSQL), so fragments with no ``%`` emit byte-identical DDL.
"""

import unittest

from odoo.db.schema import create_index


class _RecordingCursor:
    """Reports every index as missing and records the statements it is given."""

    def __init__(self):
        self.rowcount = 0
        self.statements = []

    def execute(self, query, params=None, log_exceptions=True):
        code = getattr(query, "code", query)
        self.statements.append(code)


class TestCreateIndexPercentEscaping(unittest.TestCase):
    def _create(self, **kwargs):
        cr = _RecordingCursor()
        create_index(cr, "idx", "tbl", **kwargs)  # type: ignore[arg-type]
        return cr.statements[-1]

    def test_percent_in_where_clause(self):
        code = self._create(expressions=['"name"'], where="name LIKE 'a%'")
        self.assertIn("WHERE name LIKE 'a%%'", code)

    def test_percent_in_expression(self):
        code = self._create(expressions=["(name || '100%')"])
        self.assertIn("(name || '100%%')", code)

    def test_percent_in_both(self):
        code = self._create(expressions=["(name || '%')"], where="name LIKE '%x%'")
        self.assertIn("(name || '%%')", code)
        self.assertIn("WHERE name LIKE '%%x%%'", code)

    def test_fragments_without_percent_are_unchanged(self):
        code = self._create(expressions=['"name"'], where="state = 'open'")
        self.assertIn('USING btree ("name")', code)
        self.assertIn("WHERE state = 'open'", code)
        self.assertNotIn("%", code)

    def test_multiple_expressions_are_each_escaped(self):
        code = self._create(expressions=["a || '%'", "b || '%'"])
        self.assertIn("a || '%%', b || '%%'", code)


if __name__ == "__main__":
    unittest.main()
