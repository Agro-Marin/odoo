#!/usr/bin/env python3
"""Gate ``test_architecture_doc.py`` against the failure it exists to prevent.

That suite pins ``doc/architecture/ARCHITECTURE.md`` against the code. But a doc test of the
shape::

    for ref in re.findall(PATTERN, DOC):
        self.assertTrue(resolves(ref))

is **green on a page that says nothing**. It cannot distinguish "every reference
resolves" from "the pattern matched no references" -- so it stops constraining
the page the moment the prose is reworded past its regex, and reports success
while doing it. That is the same "green because it never ran" failure ADR-0009
was written about, one level up: the gate on the docs had no gate.

Audited by running the whole suite against a DOC that makes no claims, **four**
tests survived that should not have -- ``test_adrs_exist``,
``test_documented_commands_exist``, ``test_referenced_workflows_exist`` and
``test_named_source_paths_exist``. Each now guards its extraction. This file
keeps that property: swap the page for one that says nothing, and every test
that claims to read it must fail.

Some survivors are correct and expected:

* **code-only** -- the assertion is about the tree, a workflow, a README or
  another file's restated count, and never touches ``DOC``;
* **negative** -- ``assertNotIn("...", DOC)`` is vacuously true of empty text by
  construction. Those are "the page must not say X" guards; their teeth are
  proven by mutating the text *in*, not out.
* **conditional** -- the test iterates a construct the page is ALLOWED to carry
  none of, so an empty match set is a legitimate state rather than a rotted
  pattern. Guarding it with "assert we found at least one" would force the
  document to keep carrying the construct, which for line-number citations is
  the opposite of what we want. These must instead self-test their extractor
  against a synthetic subject, so a broken pattern is still caught.

Both kinds are listed below by name. A new one must be added deliberately, which
is the point: adding a name here is a claim that the test does not read the page,
and it is checked -- :meth:`test_listed_survivors_really_do_not_read_the_doc`
fails if a listed test does read it.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_architecture_doc as doc_suite

#: A page that asserts nothing about this repository.
EMPTY_DOC = "# Nothing\n\nThis page makes no claims.\n"

#: Tests that legitimately pass against ``EMPTY_DOC``, with why.
#:
#: ``code-only``: asserts an invariant of the tree, a workflow, a README or a
#: count restated in another file, and never reads ``DOC``.
#: ``negative``: an ``assertNotIn`` on ``DOC``, which empty text satisfies.
#: ``conditional``: iterates a construct the page may legitimately carry none
#: of; its extractor is self-tested instead of hit-counted.
EXPECTED_SURVIVORS: dict[str, str] = {
    # counts this page restates elsewhere -- checked against the code, not the page
    "TestCountsRestatedElsewhere.test_checker_docstring": "code-only",
    "TestCountsRestatedElsewhere.test_metadata_call_site_figures": "code-only",
    "TestCountsRestatedElsewhere.test_metadata_fan_in_figures": "code-only",
    "TestCountsRestatedElsewhere.test_workflow_comment": "code-only",
    # architecture.yml invariants
    "TestGateInventoryIsWiredShut.test_annotate_condition_covers_every_step": "code-only",
    "TestGateInventoryIsWiredShut.test_every_gate_step_is_blocking": "code-only",
    "TestGateInventoryIsWiredShut.test_no_gate_is_described_as_unwired": "negative",
    # the recovered call graph lives in http/README.md, not on this page
    "TestHttpCallGraphIsRecoverable.test_every_named_ir_http_hook_exists": "code-only",
    "TestHttpCallGraphIsRecoverable.test_every_named_request_method_exists": "code-only",
    "TestHttpCallGraphIsRecoverable.test_the_graph_is_actually_in_it": "code-only",
    # the DB-backed lifecycle tests must exist and be imported
    "TestHttpLifecycle.test_ordering_claims_have_a_runtime_test": "code-only",
    "TestHttpLifecycle.test_the_runtime_test_is_registered": "code-only",
    # the composition table's cells that are properties of the gate, not the
    # page: the table's own rows are asserted by test_every_cell_re_derives,
    # which does read DOC and does fail against an empty page.
    "TestCompositionTable.test_only_basemodel_is_recordset_aware": "code-only",
    "TestCompositionTable.test_the_ratchet_backs_every_column_that_can_regress": "code-only",
    "TestCompositionTable.test_units_are_file_level_not_bases": "code-only",
    # the design rule's mechanics: leaves, owners and declarations in the tree
    "TestCompositionDesignRule.test_the_cursor_counters_have_an_owner": "code-only",
    "TestCompositionDesignRule.test_the_declaration_is_what_moves_the_graph": "code-only",
    "TestCompositionDesignRule.test_the_registry_leaves_are_leaves": "code-only",
    # The document deliberately carries no ``file.py:N`` citation -- a pinned
    # line number in a file that keeps being refactored is the drift this test
    # exists to catch, so the last one was removed rather than repaired. The
    # loop is therefore empty against the real page as well as an empty one;
    # its vacuity guard is a self-test of the regex, not a count of hits.
    "TestCitationsResolve.test_line_number_citations_resolve": "conditional",
    # orm/__init__.py's docstring against the gate
    "TestOrmDocstringAgreesWithGate.test_every_orm_member_is_documented": "code-only",
    "TestOrmDocstringAgreesWithGate.test_layer0_section_matches_the_contract": "code-only",
    "TestPatchModuleConvention.test_every_registered_patch_exposes_the_hook": "code-only",
    "TestPinnedCyclesAndRemovals.test_the_backtick_note_is_not_reinstated": "negative",
    "TestPinnedViolations.test_no_new_violations": "code-only",
    # the six decomposed monoliths are named in the test, not read off the page:
    # the ``Identity`` bullet that used to list them was prose restating the tree
    "TestPosture.test_named_monoliths_are_no_longer_monoliths": "code-only",
    "TestPosture.test_sql_db_is_gone": "code-only",
    "TestReferencedArtifacts.test_ci_path_filter_covers_every_scanned_tree": "code-only",
    # the integration lane's shape, asserted against the workflow itself: the
    # boundary job must provision no database, and each suite must get its own
    # -d. Both are properties of integration_tests.yml, not of the page.
    "TestTheEnforcedClaimIsBounded.test_the_boundary_job_really_has_no_database": "code-only",
    "TestTheEnforcedClaimIsBounded.test_each_suite_gets_its_own_database": "code-only",
}


def _suite() -> unittest.TestSuite:
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for name in sorted(dir(doc_suite)):
        obj = getattr(doc_suite, name)
        if isinstance(obj, type) and issubclass(obj, unittest.TestCase):
            suite.addTests(loader.loadTestsFromTestCase(obj))
    return suite


def _short_id(case: unittest.TestCase) -> str:
    return case.id().split(".", 1)[1]


def _run_against(text: str) -> tuple[set[str], set[str]]:
    """Run the doc suite with ``DOC`` replaced. Returns ``(passed, all)``."""
    original_doc, original_flat = doc_suite.DOC, doc_suite.DOC_FLAT
    doc_suite.DOC = text
    doc_suite.DOC_FLAT = " ".join(text.split())
    try:
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(
            _suite()
        )
    finally:
        doc_suite.DOC, doc_suite.DOC_FLAT = original_doc, original_flat
    failed = {c[0].id().split(".", 1)[1] for c in result.failures}
    failed |= {c[0].id().split(".", 1)[1] for c in result.errors}
    every = {_short_id(case) for case in _suite()}
    return every - failed, every


class TestDocSuiteIsNotVacuous(unittest.TestCase):
    def test_the_suite_passes_against_the_real_page(self) -> None:
        """Control: without it, a suite that always fails would look rigorous.

        ``read_docs()``, not ``DOC_PATH.read_text()``: the documentation is a
        front door plus its views, and reading the front door alone would fail
        every assertion about content that lives in a view — reporting the split
        as a broken suite rather than as a moved sentence.
        """
        passed, every = _run_against(doc_suite.read_docs())
        self.assertEqual(passed, every, f"failing: {sorted(every - passed)}")

    def test_only_the_listed_tests_survive_an_empty_page(self) -> None:
        passed, every = _run_against(EMPTY_DOC)
        unexpected = passed - set(EXPECTED_SURVIVORS)
        self.assertEqual(
            sorted(unexpected),
            [],
            "these tests pass against a page that says nothing, so they no "
            "longer constrain it -- guard the extraction (assert it found "
            "something) or add the test to EXPECTED_SURVIVORS with a reason: "
            f"{sorted(unexpected)}",
        )
        gone = set(EXPECTED_SURVIVORS) - every
        self.assertEqual(
            sorted(gone),
            [],
            f"EXPECTED_SURVIVORS names tests that no longer exist: {sorted(gone)}",
        )

    def test_listed_survivors_really_do_not_read_the_doc(self) -> None:
        """A ``code-only`` entry is a claim, so check it.

        If a listed test *does* read the page, listing it silently excuses a
        real vacuity. ``negative`` entries are exempt: reading ``DOC`` is the
        whole point of an ``assertNotIn``.
        """
        import inspect

        for short, why in EXPECTED_SURVIVORS.items():
            if why in ("negative", "conditional"):
                continue
            cls_name, method_name = short.split(".")
            method = getattr(getattr(doc_suite, cls_name), method_name)
            source = inspect.getsource(method)
            body = source.split('"""')[-1] if '"""' in source else source
            self.assertNotIn(
                "DOC",
                body,
                f"{short} is listed as code-only but reads DOC; either it is "
                f"vacuous and needs a guard, or it should be marked negative",
            )

    def test_every_expected_survivor_has_a_known_reason(self) -> None:
        self.assertEqual(
            set(EXPECTED_SURVIVORS.values())
            - {"code-only", "negative", "conditional"},
            set(),
        )

    def test_conditional_survivors_self_test_their_extractor(self) -> None:
        """A ``conditional`` entry is excused the hit count, not the guard.

        It must still prove its pattern matches a synthetic subject, or a
        rotted regex and an empty document are indistinguishable — which is the
        exact confusion this whole file exists to prevent.
        """
        import inspect

        for short, why in EXPECTED_SURVIVORS.items():
            if why != "conditional":
                continue
            cls_name, method_name = short.split(".")
            source = inspect.getsource(
                getattr(getattr(doc_suite, cls_name), method_name)
            )
            self.assertIn(
                "has rotted",
                source,
                f"{short} is listed as conditional but does not self-test its "
                f"extractor; an empty match set is then indistinguishable from "
                f"a broken pattern",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
