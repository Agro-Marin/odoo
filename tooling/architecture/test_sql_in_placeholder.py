import tempfile
import textwrap
import unittest
from pathlib import Path

import sql_in_placeholder as sip


def _write(tmp: Path, name: str, body: str) -> Path:
    path = tmp / name
    path.write_text(textwrap.dedent(body))
    return path


class TestMeasure(unittest.TestCase):
    """Every case here was measured against a real cursor before being pinned.

    The gate reads zero across all four scopes, which is only worth something if
    it can still see -- so each shape it is supposed to catch is asserted here,
    and so is each shape it must leave alone.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _measure(self, body: str):
        return sip.measure([_write(self.tmp, "a.py", body)])

    # --- what it must catch -------------------------------------------------

    def test_a_query_handed_straight_to_execute_is_reported(self):
        found = self._measure(
            'cr.execute("SELECT id FROM tbl WHERE id IN %s", (ids,))'
        )
        self.assertEqual([f.kind for f in found], ["unbuilt"])

    def test_a_named_placeholder_is_reported_too(self):
        found = self._measure(
            'cr.execute("SELECT id FROM tbl WHERE id IN %(ids)s", {"ids": ids})'
        )
        self.assertEqual(len(found), 1)

    def test_not_in_is_reported(self):
        found = self._measure(
            'cr.execute("SELECT id FROM tbl WHERE id NOT IN %s", (ids,))'
        )
        self.assertEqual(len(found), 1)

    def test_the_builder_given_a_list_is_reported(self):
        found = self._measure(
            'SQL("SELECT id FROM tbl WHERE id IN %(ids)s", ids=[1, 2])'
        )
        self.assertEqual([f.kind for f in found], ["sequence"])

    def test_the_builder_given_a_recordset_ids_is_reported(self):
        found = self._measure(
            'SQL("SELECT id FROM tbl WHERE id IN %(ids)s", ids=records.ids)'
        )
        self.assertEqual([f.kind for f in found], ["sequence"])

    def test_the_builder_given_a_comprehension_is_reported(self):
        found = self._measure(
            'SQL("SELECT id FROM tbl WHERE id IN %(ids)s", ids=[r.id for r in rs])'
        )
        self.assertEqual([f.kind for f in found], ["sequence"])

    def test_a_positional_placeholder_maps_to_its_own_argument(self):
        """The second `%s` is the one bound to the list, not the first."""
        found = self._measure(
            'SQL("SELECT id FROM tbl WHERE a IN %s AND b IN %s", (1, 2), [3, 4])'
        )
        self.assertEqual(len(found), 1)

    # --- what it must leave alone -------------------------------------------

    def test_the_builder_given_a_tuple_is_correct(self):
        """The builder expands a tuple into `(%s, %s)`; this is the idiom."""
        self.assertEqual(
            self._measure(
                'SQL("SELECT id FROM tbl WHERE id IN %(ids)s", ids=tuple(records.ids))'
            ),
            [],
        )

    def test_a_tuple_display_is_correct(self):
        self.assertEqual(
            self._measure('SQL("SELECT id FROM tbl WHERE t IN %(t)s", t=("a", "b"))'),
            [],
        )

    def test_a_composed_subquery_is_correct(self):
        self.assertEqual(
            self._measure(
                'SQL("SELECT id FROM tbl WHERE id IN %s", query.subselect())'
            ),
            [],
        )

    def test_an_unresolvable_argument_is_left_alone(self):
        """A bare name is not evidence; see the docstring on why."""
        self.assertEqual(
            self._measure('SQL("SELECT id FROM tbl WHERE id IN %(ids)s", ids=ids)'),
            [],
        )

    def test_any_over_a_list_is_the_other_correct_spelling(self):
        self.assertEqual(
            self._measure('cr.execute("SELECT id FROM tbl WHERE id = ANY(%s)", [ids])'),
            [],
        )

    def test_prose_carrying_the_english_word_in_is_not_a_query(self):
        """Three real messages that a case-insensitive keyword test admitted."""
        for message in (
            '_("Here is your Receipt for %(pos)s amounting in %(amount)s from %(co)s")',
            '_logger.warning("rate limit: %s/%s in %ss from %s", a, b, c, d)',
            '_("Field %(name)s used in %(use)s is present in view but is in select multi.")',
        ):
            with self.subTest(message=message):
                self.assertEqual(self._measure(message), [])

    def test_a_literal_python_formats_before_it_is_a_query_is_not_a_placeholder(self):
        """calendar_recurrence's CHECK builds SQL literals, not placeholders."""
        self.assertEqual(
            self._measure(
                'models.Constraint("CHECK (weekday IN %s AND byday IN %s)" % (a, b))'
            ),
            [],
        )

    def test_a_query_text_returned_for_a_builder_elsewhere_is_left_alone(self):
        """Core's own shape: the text in one method, `SQL()` in another."""
        self.assertEqual(
            self._measure(
                'def q():\n'
                '    return "SELECT res_id FROM ir_model_data WHERE res_id IN %(res_ids)s"\n'
            ),
            [],
        )

    def test_an_empty_tree_is_refused_rather_than_reported_as_clean(self):
        with self.assertRaises(RuntimeError):
            sip.measure(src=self.tmp)


if __name__ == "__main__":
    unittest.main()
