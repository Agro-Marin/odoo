import unittest

from odoo.db.schema import create_index


class _RecordingCursor:
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
