from odoo.orm.domain import Domain
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


class TestSearchDisplayNameStored(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["test_orm.display"]
        cls.records = cls.Model.create([{}, {}, {}])
        cls.env.flush_all()
        cls.records[0].display_name = "alpha"
        cls.records[1].display_name = "beta"
        cls.records[2].display_name = "alpha"
        cls.env.flush_all()
        cls.env.invalidate_all()

    def _search(self, operator, value):
        domain = Domain("id", "in", self.records.ids) & Domain(
            "display_name", operator, value
        )
        return self.Model.search(domain)

    def test_equality_selects_only_the_matching_records(self):
        self.assertEqual(self._search("=", "alpha"), self.records[0] | self.records[2])
        self.assertEqual(self._search("=", "beta"), self.records[1])
        self.assertFalse(self._search("=", "nothing-matches-this"))

    def test_inequality_is_the_complement(self):
        self.assertEqual(self._search("!=", "alpha"), self.records[1])

    def test_like_operators_reach_the_column(self):
        self.assertEqual(
            self._search("ilike", "ALPH"), self.records[0] | self.records[2]
        )
        self.assertFalse(self._search("ilike", "zzz"))

    def test_null_comparand_selects_the_records_without_a_value(self):
        self.assertFalse(self._search("=", False))
        self.assertEqual(self._search("!=", False), self.records)

    def test_a_condition_and_its_negation_partition_the_records(self):
        for operator, value in [
            ("=", "alpha"),
            ("ilike", "alph"),
            ("in", ["alpha", "beta"]),
            ("=", False),
        ]:
            with self.subTest(operator=operator, value=value):
                matched = self._search(operator, value)
                negated = self.Model.search(
                    Domain("id", "in", self.records.ids)
                    & ~Domain("display_name", operator, value)
                )
                self.assertFalse(
                    matched & negated,
                    "a record satisfies both the condition and its negation",
                )
                self.assertEqual(
                    matched | negated,
                    self.records,
                    "a record satisfies neither the condition nor its negation",
                )

    def test_both_evaluators_agree(self):
        for operator, value in [
            ("=", "alpha"),
            ("!=", "alpha"),
            ("ilike", "alph"),
            ("in", ["alpha"]),
            ("=", False),
        ]:
            with self.subTest(operator=operator, value=value):
                condition = Domain("display_name", operator, value)
                self.assertEqual(
                    self._search(operator, value),
                    self.records.filtered_domain(condition),
                    "search() and filtered_domain() disagree",
                )


class TestSearchDisplayNameUnsearchable(TransactionCase):
    def test_condition_does_not_restrict(self):
        model = self.env["domain.bool"]
        self.assertFalse(model._rec_name)
        self.assertFalse(model._rec_names_search)
        self.assertFalse(model._fields["display_name"].is_column)
        records = model.create([{}, {}])
        self.env.flush_all()
        scoped = Domain("id", "in", records.ids)
        with mute_logger("odoo.models"):
            self.assertEqual(
                model.search(scoped & Domain("display_name", "=", "nothing")),
                records,
                "an unsearchable display_name must not restrict",
            )

    def test_name_search_still_lists_the_records(self):
        model = self.env["domain.bool"]
        model.create([{}, {}])
        self.env.flush_all()
        with mute_logger("odoo.models"):
            self.assertTrue(model.name_search("anything"))
