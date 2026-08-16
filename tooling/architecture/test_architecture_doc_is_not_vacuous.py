#!/usr/bin/env python3


from __future__ import annotations

import io
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_architecture_doc as doc_suite

EMPTY_DOC = "# Nothing\n\nThis page makes no claims.\n"

EXPECTED_SURVIVORS: dict[str, str] = {
    "TestAddonSuiteFigures.test_every_prose_figure_is_fresh": "code-only",
    "TestCountsRestatedElsewhere.test_checker_docstring": "code-only",
    "TestCountsRestatedElsewhere.test_metadata_fan_in_figures": "code-only",
    "TestCountsRestatedElsewhere.test_workflow_comment": "code-only",
    "TestGateInventoryIsWiredShut.test_annotate_condition_covers_every_step": "code-only",
    "TestGateInventoryIsWiredShut.test_every_gate_step_is_blocking": "code-only",
    "TestGateInventoryIsWiredShut.test_no_gate_is_described_as_unwired": "negative",
    "TestHttpCallGraphIsRecoverable.test_every_named_ir_http_hook_exists": "code-only",
    "TestHttpCallGraphIsRecoverable.test_every_named_request_method_exists": "code-only",
    "TestHttpCallGraphIsRecoverable.test_the_graph_is_actually_in_it": "code-only",
    "TestHttpLifecycle.test_ordering_claims_have_a_runtime_test": "code-only",
    "TestHttpLifecycle.test_the_runtime_test_is_registered": "code-only",
    "TestCompositionTable.test_only_basemodel_is_recordset_aware": "code-only",
    "TestCompositionTable.test_the_ratchet_backs_every_column_that_can_regress": "code-only",
    "TestCompositionTable.test_units_are_file_level_not_bases": "code-only",
    "TestCompositionDesignRule.test_the_cursor_counters_have_an_owner": "code-only",
    "TestCompositionDesignRule.test_the_declaration_is_what_moves_the_graph": "code-only",
    "TestCompositionDesignRule.test_the_registry_leaves_are_leaves": "code-only",
    "TestCitationsResolve.test_line_number_citations_resolve": "conditional",
    "TestOrmDocstringAgreesWithGate.test_every_orm_member_is_documented": "code-only",
    "TestOrmDocstringAgreesWithGate.test_layer0_section_matches_the_contract": "code-only",
    "TestPatchModuleConvention.test_every_registered_patch_exposes_the_hook": "code-only",
    "TestPinnedCyclesAndRemovals.test_the_backtick_note_is_not_reinstated": "negative",
    "TestPinnedViolations.test_no_new_violations": "code-only",
    "TestPosture.test_named_monoliths_are_no_longer_monoliths": "code-only",
    "TestPosture.test_sql_db_is_gone": "code-only",
    "TestReferencedArtifacts.test_ci_path_filter_covers_every_scanned_tree": "code-only",
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


_SUBTEST_PARAMS = re.compile(r" \(.*\)$")


def _short_id(case: unittest.TestCase) -> str:
    return case.id().split(".", 1)[1]


def _normalise(test_id: str) -> str:

    return _SUBTEST_PARAMS.sub("", test_id.split(".", 1)[1])


def _run_against(text: str) -> tuple[set[str], set[str]]:
    original_doc, original_flat = doc_suite.DOC, doc_suite.DOC_FLAT
    doc_suite.DOC = text
    doc_suite.DOC_FLAT = " ".join(text.split())
    try:
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(
            _suite()
        )
    finally:
        doc_suite.DOC, doc_suite.DOC_FLAT = original_doc, original_flat
    failed = {_normalise(c[0].id()) for c in result.failures}
    failed |= {_normalise(c[0].id()) for c in result.errors}
    every = {_short_id(case) for case in _suite()}
    return every - failed, every


class TestDocSuiteIsNotVacuous(unittest.TestCase):
    def test_the_suite_passes_against_the_real_page(self) -> None:

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
            set(EXPECTED_SURVIVORS.values()) - {"code-only", "negative", "conditional"},
            set(),
        )

    def test_conditional_survivors_self_test_their_extractor(self) -> None:

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
