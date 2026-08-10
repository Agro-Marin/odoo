import ast
import logging
from pathlib import Path
from textwrap import dedent

from odoo.tests.common import BaseCase, no_retry

from . import _checker_translated_unique as checker
from . import _py_scan, lint_case

_logger = logging.getLogger(__name__)

FIX = (
    "A translated column is jsonb, so UNIQUE over it compares whole translation "
    "documents and stops matching as soon as one row carries a language the "
    "other does not. Declare name_uniq_index(...) from "
    "odoo/addons/base/models/catalog_mixin.py instead -- it indexes the source "
    "term. Pass nulls_distinct=True when converting an existing constraint, so "
    "only the comparison changes."
)


class TestTranslatedUnique(lint_case.LintCase):
    """No UNIQUE may be declared over a translated column.

    The floor is 0 and is meant to stay there: the 21 rules that were in this
    state were fixed in the same series that added this gate, so there is no
    debt for a new one to hide behind.
    """

    def test_no_unique_over_a_translated_column(self):
        paths = [
            path
            for path in lint_case.module_file_paths()
            if path.endswith(".py")
            and lint_case.is_core_path(path)
            and "__pycache__" not in path
        ]
        units = []
        models = 0
        rules = 0
        for path in paths:
            try:
                tree = ast.parse(Path(path).read_bytes(), path)
            except OSError, SyntaxError, ValueError:
                continue
            infos = checker.collect(tree)
            if not infos:
                continue
            # Test models are excluded from the *findings* but not from the
            # inheritance map: a real model may take a translated field from a
            # mixin that a test module also uses.
            models += len(infos)
            rules += sum(len(info.rules) for info in infos)
            units.append((path, infos))

        _logger.info(
            "%s model classes across %s files, %s uniqueness rules considered",
            models,
            len(units),
            rules,
        )
        # A scan that reaches nothing reports success just as loudly as one that
        # finds nothing, so pin that it actually ran.
        self.assertGreater(models, 1000, "the scan reached almost no models")
        self.assertGreater(rules, 100, "the scan found almost no constraints")

        found = [
            violation
            for violation in checker.violations(units)
            if not _py_scan.is_test_path(violation.path)
        ]
        self.assert_ratchet(found, 0, "UNIQUE rule(s) over a translated column", FIX)


@no_retry
class TestTranslatedUniqueChecker(BaseCase):
    """The detector's own behaviour, so a gate that stops detecting is caught.

    A whole-tree gate whose floor is 0 passes both when the tree is clean and
    when the checker has quietly broken. These pin the difference.
    """

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
        """The cross-file case a per-file checker cannot reach."""
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
            class CatalogMixin(models.AbstractModel):
                _name = "catalog.mixin"
                name = fields.Char(required=True, translate=True)
            """,
            concrete="""
            class Thing(models.Model):
                _name = "a.thing"
                _inherit = ["catalog.mixin"]
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
