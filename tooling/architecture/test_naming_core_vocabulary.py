"""The core vocabulary gate, and the four ways a zero-floor gate goes vacuous.

A gate whose floor is zero passes by finding nothing, which is also what it does
when it has stopped looking. Every assertion here is aimed at that: the scan
reaches files, the predicate still recognises what it is named for, the allowlist
holds only names the scan would otherwise report, and the tree really is clean.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import naming_core_vocabulary as ncv
import naming_vocabulary as nv


class TestTheScanReachesSomething(unittest.TestCase):
    def test_it_refuses_an_empty_tree_rather_than_reporting_zero(self):
        with self.assertRaises(RuntimeError) as caught:
            ncv.measure(Path(__file__).with_name("__pycache__"))
        self.assertIn("refusing", str(caught.exception))

    def test_the_scan_reaches_the_core_package(self):
        files = ncv.core_files()
        self.assertGreater(
            len(files),
            400,
            "the core scan yielded almost nothing; every assertion below would "
            "then pass by looking at an empty list",
        )

    def test_the_framework_tree_is_in_scope(self):
        # odoo/tests is the test framework, not a suite. It is the one tree
        # `_sources.is_test_path` gets wrong, and the reason this gate has its
        # own file-selection rule instead of borrowing that one.
        files = {p.name for p in ncv.core_files() if p.is_relative_to(ncv.FRAMEWORK)}
        self.assertIn("http.py", files)
        self.assertIn(
            "test_cursor.py",
            files,
            "test_cursor.py defines TestCursor, a cursor -- excluding it by its "
            "filename is the mistake this gate exists not to repeat",
        )

    def test_a_real_suite_tree_is_out_of_scope(self):
        files = ncv.core_files()
        self.assertFalse(
            [p for p in files if "orm" in p.parts and "tests" in p.parts],
            "odoo/orm/tests is a suite and is governed by nothing here",
        )


class TestThePredicateStillRecognisesWhatItIsNamedFor(unittest.TestCase):
    def test_a_leading_abolished_verb_is_reported(self):
        hit = ncv.classify_name("_validate_thing")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "leading")

    def test_an_assemble_verb_is_reported_without_a_payload_suffix(self):
        # The whole reason this gate is not a --roots flag on the sibling:
        # nv.classify returns None here, and ADR-0083 renamed 38 of these.
        self.assertIsNone(nv.classify("_build_server"))
        hit = ncv.classify_name("_build_server")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "assemble")

    def test_a_bare_assemble_verb_is_reported(self):
        self.assertIsNone(nv.classify("make"))
        hit = ncv.classify_name("make")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "bare")

    def test_a_bare_non_assemble_verb_is_not_reported(self):
        # `delete` alone is a Protocol member in orm/runtime/backend.py and the
        # contract in libs/password.py's neighbourhood. §2.4.6 [review], and the
        # line this gate deliberately does not cross.
        self.assertIsNone(ncv.classify_name("delete"))

    def test_a_dunder_is_not_a_naming_choice(self):
        self.assertIsNone(ncv.classify_name("__init__"))

    def test_a_canonical_name_is_not_reported(self):
        self.assertIsNone(ncv.classify_name("_prepare_invoice_vals"))
        self.assertIsNone(ncv.classify_name("_get_candidate"))


class TestTheAllowlistIsArgued(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(ncv.ALLOWLIST.read_text(encoding="utf-8"))

    def test_every_entry_carries_a_reason(self):
        for name, why in self.raw["names"].items():
            self.assertGreater(
                len(why), 20, f"{name} is allowed with no argument, only a string"
            )

    def test_no_entry_is_dead_weight(self):
        # An allowlist entry that no definition answers to is a name nobody can
        # find and nobody will delete. Every one must be a name the scan would
        # otherwise report.
        allowed = set(self.raw["names"])
        seen = set()
        for path in ncv.core_files():
            src = path.read_text(encoding="utf-8", errors="ignore")
            seen |= {name for name in allowed if f"def {name}(" in src}
        self.assertEqual(
            allowed - seen,
            set(),
            "these names are allowed and nothing in core defines them -- either "
            "the definition moved or the entry outlived its rename",
        )

    def test_every_entry_would_otherwise_be_reported(self):
        # The allowlist serves both readers. An entry earns its place if the
        # gate would flag the name, or if the candidate finder would raise it as
        # a question -- `fetch` is the second kind, and the entry is what makes
        # it a reservation rather than an open question.
        unreachable = {
            name
            for name in self.raw["names"]
            if ncv.classify_name(name) is None and not ncv.is_bare_abolished(name)
        }
        self.assertEqual(
            unreachable,
            set(),
            "these names are allowed and neither the gate nor the candidate "
            "finder would have raised them, so the entry hides nothing and "
            "reads as a rule that does not exist",
        )


class TestItCatchesAPlantedRegression(unittest.TestCase):
    """Zero on the real tree is also what a broken scan reports.

    Every other assertion here is about the predicate or the file list. These
    two run the gate end to end over a tree that does contain the thing it is
    looking for, which is the only way "0" is evidence of anything.
    """

    def plant(self, source: str) -> list[ncv.Violation]:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "planted.py").write_text(source, encoding="utf-8")
            return ncv.measure(Path(tmp))

    def test_an_assemble_verb_with_no_payload_suffix_fails_the_gate(self):
        found = self.plant("def _build_server(app):\n    return app\n")
        self.assertEqual([v.name for v in found], ["_build_server"])
        self.assertEqual(found[0].kind, "assemble")

    def test_a_bare_verb_and_a_nested_closure_both_fail_the_gate(self):
        found = self.plant(
            "class Speedscope:\n"
            "    def make(self):\n"
            "        def make_node_info(node):\n"
            "            return node\n"
            "        return make_node_info\n"
        )
        self.assertEqual(sorted(v.name for v in found), ["make", "make_node_info"])

    def test_an_override_of_a_third_party_name_does_not_fail_the_gate(self):
        # WSGIRequestHandler.make_environ is werkzeug's; renaming it is not a
        # rename, it is a silent unhooking.
        found = self.plant(
            "class Handler:\n"
            "    def make_environ(self):\n"
            "        return super().make_environ()\n"
        )
        self.assertEqual(found, [])

    def test_an_allowlisted_name_does_not_fail_the_gate(self):
        found = self.plant("def append_paths(self, paths):\n    return paths\n")
        self.assertEqual(found, [])


class TestRealTree(unittest.TestCase):
    def test_nothing_outside_the_framework_tree_is_left(self):
        # ADR-0083 took every part of the core package except odoo/tests to zero
        # on this vocabulary, and left that tree to the sweep already running
        # inside it. The COUNT of what remains there is the naming_core floor's
        # job -- it is six at the time of writing and goes to zero the moment
        # that sweep lands, so asserting it here would break on their commit and
        # again on the re-bank. What does not move is the boundary: a finding
        # anywhere else is a regression whatever the floor says.
        outside = [v for v in ncv.measure() if "/tests/" not in v.path]
        self.assertEqual(
            [str(v) for v in outside],
            [],
            "a finding outside odoo/tests. Rename it, or argue it into "
            "naming_core_allowlist.json with the reason it survives — the "
            "floor is for the framework sweep's remainder and covers nothing "
            "else.",
        )

    def test_the_candidate_population_is_reported_and_not_gated(self):
        # It is allowed to shrink to nothing -- that would mean somebody read
        # them all -- but it must not be silently empty because the finder broke.
        found = ncv.candidates()
        for item in found:
            self.assertEqual(item.kind, "bare-review")
        self.assertNotIn(
            "fetch",
            {item.name for item in found},
            "fetch is settled by the allowlist and is not a candidate",
        )


if __name__ == "__main__":
    unittest.main()
