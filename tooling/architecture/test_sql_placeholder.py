#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import sql_placeholder


class GateCase(unittest.TestCase):
    def findings(self, source: str, name: str = "models/thing.py"):
        with TemporaryDirectory() as directory:
            path = Path(directory) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
            found, _sites = sql_placeholder.measure([Path(directory)])
        return found

    def kinds(self, source: str, name: str = "models/thing.py"):
        return sorted(f.kind for f in self.findings(source, name))


class TestTheRegressionsItWasBuiltFor(GateCase):
    def test_a_clause_appended_to_a_query_built_elsewhere(self):
        self.assertEqual(
            self.kinds(
                "def _get_last_sequence_domain(self):\n"
                '    where_string += " AND move_type IN %(move_type)s"\n'
            ),
            ["in-placeholder"],
        )

    def test_a_report_filter_that_is_only_sometimes_appended(self):
        self.assertEqual(
            self.kinds(
                "sql = TEMPLATE.format(\n"
                "    where_journals=(journals and 'AND j.id IN %(journal_ids)s') or \"\",\n"
                ")\n"
            ),
            ["in-placeholder"],
        )

    def test_every_occurrence_in_one_method_is_reported(self):
        source = (
            "conditions = [\n"
            + "".join(
                f'    "EXTRACT(YEAR FROM t.d) IN %s AND x = {i}",\n' for i in range(9)
            )
            + "]\n"
        )
        self.assertEqual(len(self.findings(source)), 9)

    def test_a_tuple_parameter_no_query_text_can_reveal(self):
        self.assertEqual(
            self.kinds(
                "self.env.cr.execute(\n"
                '    "SELECT id FROM t WHERE list_id = ANY(%s)", (tuple(self.ids),)\n'
                ")\n"
            ),
            ["tuple-parameter"],
        )

    def test_a_tuple_among_other_parameters(self):
        self.assertEqual(
            self.kinds("cr.execute(QUERY, (self.id, tuple(src.ids), self.id))\n"),
            ["tuple-parameter"],
        )

    def test_a_tuple_in_a_named_parameter_map(self):
        self.assertEqual(
            self.kinds('cr.execute(QUERY, {"ids": tuple(self.ids)})\n'),
            ["tuple-parameter"],
        )


class TestWhatItMustNotReport(GateCase):
    def test_prose_is_not_a_statement(self):
        for source in (
            '_logger.info("assets generated in %s seconds", elapsed)\n',
            'raise UserError("no record in %(model)s matched")\n',
        ):
            with self.subTest(source=source):
                self.assertEqual(self.findings(source), [])

    def test_a_docstring_describing_the_defect_is_not_the_defect(self):
        for source in (
            '"""Do not write WHERE id IN %s -- psycopg 3 cannot bind it."""\n',
            'class C:\n    """Do not write WHERE id IN %s here either."""\n',
            'def f():\n    """WHERE id IN %s is the shape this forbids."""\n',
            'async def f():\n    """WHERE id IN %s is the shape this forbids."""\n',
        ):
            with self.subTest(source=source):
                self.assertEqual(self.findings(source), [])

    def test_a_statement_below_a_docstring_is_still_read(self):
        source = (
            '"""WHERE id IN %s is the shape this forbids."""\n'
            'cr.execute("SELECT id FROM t WHERE id IN %s", ids)\n'
        )
        self.assertEqual(self.kinds(source), ["in-placeholder"])

    def test_a_bare_string_expression_is_not_a_docstring(self):
        source = (
            '"""Module prose."""\n'
            'query = "SELECT id FROM t WHERE id IN %s"\n'
            "cr.execute(query, ids)\n"
        )
        self.assertEqual(self.kinds(source), ["in-placeholder"])

    def test_the_supported_spelling_expands_the_placeholder(self):
        self.assertEqual(
            self.findings('cr.execute(SQL("SELECT id FROM t WHERE id IN %s", tup))\n'),
            [],
        )

    def test_a_python_percent_format_is_not_a_bind(self):
        self.assertEqual(
            self.findings(
                'C = Constraint("CHECK (weekday IN %s AND day > 0)" % (DAYS,))\n'
            ),
            [],
        )

    def test_the_parameter_container_is_not_a_parameter(self):
        for source in (
            "cr.execute(QUERY, (self.id, other_id))\n",
            "cr.execute(QUERY, tuple(collected))\n",
            "cr.execute(QUERY, [self.id])\n",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.findings(source), [])

    def test_the_repaired_form_is_clean(self):
        self.assertEqual(
            self.findings(
                'cr.execute("SELECT id FROM t WHERE id = ANY(%s)", (list(ids),))\n'
            ),
            [],
        )

    def test_a_fixture_may_take_any_shape(self):
        source = 'cr.execute("SELECT 1 FROM t WHERE id IN %s", (tuple(ids),))\n'
        self.assertEqual(self.kinds(source), ["in-placeholder", "tuple-parameter"])
        for name in ("tests/test_thing.py", "test_thing.py", "tests/common.py"):
            with self.subTest(name=name):
                self.assertEqual(self.findings(source, name), [])


class TestItRefusesAnEmptyScan(GateCase):
    def test_a_tree_with_no_cursor_execute_reports_no_inputs(self):
        with TemporaryDirectory() as directory:
            (Path(directory) / "empty.py").write_text("x = 1\n", encoding="utf-8")
            findings, sites = sql_placeholder.measure([Path(directory)])
        self.assertEqual(findings, [])
        self.assertEqual(sites, 0, "zero inputs is what the refusal is written on")

    def test_a_tree_with_one_is_not_empty(self):
        with TemporaryDirectory() as directory:
            (Path(directory) / "m.py").write_text(
                'cr.execute("SELECT 1")\n', encoding="utf-8"
            )
            _findings, sites = sql_placeholder.measure([Path(directory)])
        self.assertEqual(sites, 1)


if __name__ == "__main__":
    unittest.main()
