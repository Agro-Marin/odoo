"""Unit tests for the `unique-over-translated-column` checker.

The whole-tree half of this gate is a `_rules.CHECKERS` entry now: it rode its
own serial `ast.parse` of all 9390 core Python files, next to the parallel scan
that had already parsed every one of them.
"""

import ast
from textwrap import dedent

from odoo.tests.common import BaseCase, no_retry

from . import _checker_translated_unique as checker


@no_retry
class TestTranslatedUniqueChecker(BaseCase):
    @staticmethod
    def _units(**sources):
        return [
            (f"{name}.py", checker.collect(ast.parse(dedent(source))))
            for name, source in sources.items()
        ]

    def _findings(self, **sources):
        return list(checker.violations(self._units(**sources)))

    def test_flags_unique_over_a_translated_field(self):
        found = self._findings(
            a="""
            class Tag(models.Model):
                _name = "a.tag"
                name = fields.Char(required=True, translate=True)
                _name_uniq = models.Constraint("unique (name)", "dupe")
            """
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].columns, ("name",))

    def test_ignores_an_untranslated_field(self):
        self.assertFalse(
            self._findings(
                a="""
                class Tag(models.Model):
                    _name = "a.tag"
                    name = fields.Char(required=True)
                    _name_uniq = models.Constraint("unique (name)", "dupe")
                """
            ),
            "a varchar column compares as a value; UNIQUE is correct there",
        )

    def test_ignores_the_fixed_form(self):
        self.assertFalse(
            self._findings(
                a="""
                class Tag(models.Model):
                    _name = "a.tag"
                    name = fields.Char(translate=True)
                    _name_src_uniq = models.UniqueIndex("((name->>'en_US')) NULLS NOT DISTINCT")
                """
            ),
            "an index over the source term is the fix, not a finding",
        )

    def test_flags_a_scoped_constraint(self):
        found = self._findings(
            a="""
            class Line(models.Model):
                _name = "a.line"
                name = fields.Char(translate=True)
                _uniq = models.Constraint("unique(company_id, name)", "dupe")
            """
        )
        self.assertEqual(found[0].columns, ("name",))

    def test_flags_a_unique_index_including_a_partial_one(self):
        found = self._findings(
            a="""
            class Job(models.Model):
                _name = "a.job"
                name = fields.Char(translate=True)
                _uniq = models.UniqueIndex("(name, company_id) WHERE department_id IS NULL")
            """
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].columns, ("name",))

    def test_sees_a_field_translated_by_another_module(self):
        found = self._findings(
            base="""
            class Tag(models.Model):
                _name = "a.tag"
                name = fields.Char()
            """,
            extension="""
            class TagExtension(models.Model):
                _inherit = "a.tag"
                name = fields.Char(translate=True)
            """,
            constraint="""
            class TagConstraint(models.Model):
                _inherit = "a.tag"
                _name_uniq = models.Constraint("unique (name)", "dupe")
            """,
        )
        self.assertEqual(len(found), 1, "the three facts live in three files")

    def test_sees_a_field_translated_by_an_inherited_mixin(self):
        found = self._findings(
            mixin="""
            class MixinCatalog(models.AbstractModel):
                _name = "mixin.catalog"
                name = fields.Char(required=True, translate=True)
            """,
            concrete="""
            class Thing(models.Model):
                _name = "a.thing"
                _inherit = ["mixin.catalog"]
                _uniq = models.Constraint("unique(name, company_id)", "dupe")
            """,
        )
        self.assertEqual(len(found), 1, "translate=True is two models away")

    def test_survives_an_inherit_cycle(self):
        self._findings(
            a="""
            class Thing(models.Model):
                _name = "a.thing"
                _inherit = ["b.thing"]
            """,
            b="""
            class Other(models.Model):
                _name = "b.thing"
                _inherit = ["a.thing"]
            """,
        )

    def test_a_three_way_inherit_cycle_resolves_every_translated_field(self):
        """A one-hop cycle guard isn't enough for a cycle of length >= 3.

        `walk()` used to cache a model's field set as soon as its own
        immediate parents were not in `seen`, even mid-cycle -- so the model
        that happened to close the cycle got cached with only its own fields,
        missing the others further around the ring. Exercised directly on
        `resolve_translated` (not `violations()`, which only reports on the
        rule matching a column, and would stay silent either way): every
        model in a 3-cycle must resolve to the union of all three, not just
        a fragment.
        """
        infos = [
            checker.ClassInfo("a.thing", parents=("b.thing",), translated={"name"}),
            checker.ClassInfo("b.thing", parents=("c.thing",), translated={"label"}),
            checker.ClassInfo("c.thing", parents=("a.thing",), translated={"title"}),
        ]
        resolved = checker.resolve_translated(infos)
        all_fields = {"name", "label", "title"}
        for model in ("a.thing", "b.thing", "c.thing"):
            self.assertEqual(
                resolved.get(model, set()),
                all_fields,
                f"{model} resolved to {resolved.get(model, set())}, missing "
                "fields from elsewhere in the cycle",
            )

    def test_ignores_a_non_unique_constraint(self):
        self.assertFalse(
            self._findings(
                a="""
                class Thing(models.Model):
                    _name = "a.thing"
                    name = fields.Char(translate=True)
                    _check = models.Constraint("CHECK(name != '')", "empty")
                """
            )
        )
