from __future__ import annotations

import json
import re
import unittest

import _doc_measures
import doc_restated_counts

from ._shared import DOC, DOC_FLAT, ROOT


class TestAddonSuiteFigures(unittest.TestCase):
    @staticmethod
    def _suite(module: str) -> tuple[int, int]:
        for tree in ("addons", "odoo/addons"):
            base = ROOT / tree / module / "tests"
            if base.is_dir():
                break
        else:
            raise AssertionError(f"{module}/tests not found in either addon tree")
        lines = sum(
            len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
            for path in sorted(base.rglob("*.py"))
        )
        return _doc_measures.suite_methods(module), lines

    def test_no_page_states_a_suite_size_the_tree_does_not_hold(self) -> None:
        wrong = []
        for module, phrasings in {
            "test_orm": (
                rf"`test_orm`[^.]*?\*\*({_doc_measures.ANY_NUMBER}) test methods\*\*",
                rf"`test_orm`[^.]*?its ({_doc_measures.ANY_NUMBER}) methods",
            ),
            "stock": (rf"stock's own ({_doc_measures.ANY_NUMBER}) tests",),
            "mail": (rf"its own \*\*({_doc_measures.ANY_NUMBER})\*\*-test suite",),
        }.items():
            measured = _doc_measures.suite_methods(module)
            for phrasing in phrasings:
                for page, match in _doc_measures.stated(phrasing):
                    if _doc_measures.number_value(match.group(1)) != measured:
                        wrong.append(
                            f"{page}: {module} stated as {match.group(1)}, "
                            f"tree holds {measured}"
                        )
        self.assertEqual([], wrong, "\n  " + "\n  ".join(wrong))

    def test_the_test_orm_figure_is_measured(self) -> None:
        methods, _lines = self._suite("test_orm")
        self.assertIn(f"**{methods:,} test methods**", DOC_FLAT)

    def test_line_counts_are_not_quoted_for_these_suites(self) -> None:

        self.assertIn("Method counts, not line counts.", DOC_FLAT)
        for module in ("test_orm", "test_read_group"):
            _methods, lines = self._suite(module)
            self.assertNotIn(f"{lines:,} lines", DOC_FLAT)

    def test_every_prose_figure_is_fresh(self) -> None:
        figures = doc_restated_counts.figures_for(ROOT / "doc" / "architecture")
        self.assertTrue(figures, "no figure measures doc/architecture any more")
        problems = doc_restated_counts.check(figures)
        self.assertFalse(
            problems,
            "prose figures have drifted from what the tree measures; run "
            "`python tooling/architecture/doc_restated_counts.py --update`:\n  "
            + "\n  ".join(problems),
        )


class TestFloorMethodologyExample(unittest.TestCase):
    def test_the_example_does_not_claim_to_be_the_current_floor(self) -> None:

        floor = json.loads(
            (ROOT / "tooling" / "ratchet" / "baselines" / "pyfunclen.json").read_text(
                encoding="utf-8"
            )
        )["count"]
        self.assertIn("`pyfunclen` that day", DOC, "the example lost its dating")
        self.assertIn(
            "this table is an illustration of the method and is not maintained",
            DOC_FLAT,
        )
        self.assertNotIn(
            "= the committed floor",
            DOC,
            "the worked example claims equality with the committed floor again; "
            f"it is {floor} today and the claim will rot the next time a "
            f"function is shortened",
        )

    def test_the_quoted_budget_is_the_gates_own(self) -> None:
        src = (ROOT / "tooling" / "architecture" / "py_function_length.py").read_text(
            encoding="utf-8"
        )
        match = re.search(r"^MAX_LINES = (\d+)$", src, re.MULTILINE)
        self.assertIsNotNone(match, "py_function_length.MAX_LINES is gone")
        self.assertIn(f"*excess lines* over {match.group(1)}", DOC_FLAT)
