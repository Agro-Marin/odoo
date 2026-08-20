#!/usr/bin/env python3
"""Self-test for ``sql_placeholder.py``.

The gate exists because both shapes it hunts are invisible until the statement
runs, and each was found by someone tripping over it rather than by reading the
code. Its own failure modes are the mirror image, and each case below pins one:

* **Missing the regressions it was built from.** ``TestTheRegressionsItWasBuiltFor``
  reconstructs all four production shapes: a clause appended to a query built
  elsewhere (``l10n_cl``, which took Chilean invoicing down), a report's optional
  filter (``account_reports_cash_basis``), a wizard with nine of them
  (``agromarin``), and a tuple parameter (``mass_mailing``, which no rule reading
  the query text can see). Without these the gate is a decorative zero.
* **Reading prose as SQL.** "generated in %s seconds" is a log message. A gate
  that reports those gets switched off.
* **Flagging the supported spelling.** ``SQL("x IN %s", tup)`` expands the
  placeholder itself; reporting it would mean reporting the fix.
* **Flagging a Python ``%`` format.** ``"... IN %s" % (values,)`` writes the
  values into the statement text before Postgres sees it -- a CHECK constraint
  listing what it allows, not a bind.
* **Flagging the parameter container.** ``cr.execute(sql, (a, b))`` and
  ``cr.execute(sql, tuple(values))`` pass a sequence of parameters; that is the
  calling convention, not a tuple-valued parameter.
* **Counting a test fixture.** ``test_db_cursor`` passes tuples deliberately --
  it is the suite that pins what the driver does with one.
* **Reporting a clean zero from a scan that found nothing** -- the bug class
  ``test_every_gate_refuses_an_empty_tree`` sweeps, pinned here at the input the
  refusal guards: no cursor.execute anywhere.

Run directly (``python tooling/architecture/test_sql_placeholder.py``) or under
pytest.
"""

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
        """l10n_cl: `mixin.sequence` executes the string this method extends, so
        the placeholder and the cursor are in different modules. `AND` is the
        only keyword the fragment carries.
        """
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
        """agromarin's wizard had thirteen; reporting only the first would let a
        fix look complete while the rest still raise.
        """
        source = (
            "conditions = [\n"
            + "".join(
                f'    "EXTRACT(YEAR FROM t.d) IN %s AND x = {i}",\n' for i in range(9)
            )
            + "]\n"
        )
        self.assertEqual(len(self.findings(source)), 9)

    def test_a_tuple_parameter_no_query_text_can_reveal(self):
        """mass_mailing: `= ANY(%s)` is the correct operator and the query is
        blameless. The mistake is the value bound to it.
        """
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
    """The refusal keys on the count of cursor.execute sites, so that is what is
    pinned here. Whether `main` acts on it is `test_every_gate_refuses_an_empty
    _tree`'s job -- it copies the tree and runs the gate as a subprocess, which
    is the only way to empty `ROOT` itself; `--roots` adds to the real tree
    rather than replacing it, so a unit test cannot reach that branch honestly.
    """

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
