#!/usr/bin/env python3
"""Self-test for ``env_model_surface_check.py``.

A gate that cannot fail is decoration. These cases pin the ways this one could
lie:

* **Blindness to a real access** — ``self.env["x.y"]`` and bare ``env["x.y"]``
  must both be seen; a heuristic that only matched one would report a permanent
  green over half the surface.
* **Missing new coupling** — a model referenced from core but absent from the
  acknowledged set must fail ``--check``; that is the whole purpose.
* **Missing a decoupling** — a model in the baseline that nothing references
  anymore must also fail, so a genuine cleanup is committed rather than left
  reintroducible (the exact-ratchet discipline).
* **Over-matching** — a non-model string subscript (``config["x"]``, a plain
  dict, a dotted-but-not-model token) must not be counted.
* **Live-tree agreement** — the committed ``KNOWN_MODEL_SURFACE`` must match the
  real tree, or the gate ships already-red / already-lying.

Run directly or under pytest.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import env_model_surface_check as emsc


def _collect(src: str) -> list[tuple[str, int]]:
    collector = emsc._EnvModelCollector()
    collector.visit(ast.parse(src))
    return collector.hits


class TestCollector(unittest.TestCase):
    def test_sees_self_env_and_bare_env(self):
        models = {
            m
            for m, _ in _collect(
                'a = self.env["res.users"]\n'
                'b = env["ir.attachment"]\n'
                'c = record.env["ir.model.data"]\n'
            )
        }
        self.assertEqual(models, {"res.users", "ir.attachment", "ir.model.data"})

    def test_ignores_non_model_subscripts(self):
        hits = _collect(
            'x = config["db_name"]\n'  # not an env access
            "y = self.env[model_var]\n"  # dynamic key, not a literal
            'z = env["nodot"]\n'  # not model-shaped
            'w = data["a.b.c"]\n'  # not env
        )
        self.assertEqual(hits, [])

    def test_base_is_recognised(self):
        self.assertEqual({m for m, _ in _collect('env["base"]')}, {"base"})

    def test_dynamic_key_is_not_matched(self):
        self.assertEqual(_collect("env[model_name]"), [])


class TestDriftDetection(unittest.TestCase):
    def _report_over(self, models):
        """A report whose reaches are exactly ``models`` (one site each)."""
        report = emsc.Report(
            reaches=[emsc.Reach(m, "probe.py", i) for i, m in enumerate(models)]
        )
        report.added = report.models - emsc.KNOWN_MODEL_SURFACE
        report.removed = emsc.KNOWN_MODEL_SURFACE - report.models
        return report

    def test_new_model_is_flagged(self):
        report = self._report_over(sorted(emsc.KNOWN_MODEL_SURFACE) + ["totally.new"])
        self.assertIn("totally.new", report.added)
        self.assertFalse(report.ok)

    def test_removed_model_is_flagged(self):
        subset = sorted(emsc.KNOWN_MODEL_SURFACE)[:-1]  # drop one
        report = self._report_over(subset)
        self.assertEqual(len(report.removed), 1)
        self.assertFalse(report.ok)

    def test_exact_match_is_ok(self):
        report = self._report_over(sorted(emsc.KNOWN_MODEL_SURFACE))
        self.assertTrue(report.ok)
        self.assertFalse(report.added)
        self.assertFalse(report.removed)


class TestLiveTree(unittest.TestCase):
    def test_committed_baseline_matches_the_tree(self):
        report = emsc.check()
        self.assertEqual(
            report.added,
            set(),
            f"core reaches new addon models not in the baseline: {sorted(report.added)}",
        )
        self.assertEqual(
            report.removed,
            set(),
            f"baseline lists models no longer reached: {sorted(report.removed)}",
        )

    def test_check_returns_zero_on_a_clean_tree(self):
        self.assertEqual(emsc.main(["--check"]), 0)

    def test_every_core_package_is_scoped_or_exempt(self):
        """A new core package must join the scan or be excused with a reason.

        This gate's whole claim is that it *inventories* the framework's
        string-keyed model dependency. A package outside ``SCOPE_PACKAGES``
        cannot contribute to that inventory and cannot fail the ratchet, so an
        unlisted package silently shrinks the claim while the gate still reports
        the surface "matches the acknowledged set".

        Mirrors ``layer_check``'s ``test_core_source_covers_every_core_package``
        and ``libs_facade_check``'s ``test_every_core_package_is_scanned``: in
        each case the coverage is a hand-maintained list, and the list is the
        part that rots.
        """
        packages = {
            p.name
            for p in emsc.CORE.iterdir()
            if p.is_dir() and (p / "__init__.py").exists() and p.name != "__pycache__"
        }
        unlisted = packages - set(emsc.SCOPE_PACKAGES) - emsc.SCOPE_EXEMPT_PACKAGES
        self.assertEqual(
            unlisted,
            set(),
            f"core package(s) neither scanned nor exempt: {sorted(unlisted)} — "
            f"add to SCOPE_PACKAGES, or to SCOPE_EXEMPT_PACKAGES with a reason",
        )

    def test_scoped_and_exempt_packages_all_exist(self):
        """The opposite drift: a renamed package silently shrinking the scan."""
        for name in (*emsc.SCOPE_PACKAGES, *emsc.SCOPE_EXEMPT_PACKAGES):
            with self.subTest(package=name):
                self.assertTrue(
                    (emsc.CORE / name).is_dir(), f"{name} is listed but absent"
                )

    def test_the_two_lists_do_not_overlap(self):
        overlap = set(emsc.SCOPE_PACKAGES) & emsc.SCOPE_EXEMPT_PACKAGES
        self.assertEqual(overlap, set(), f"both scanned and exempt: {sorted(overlap)}")


if __name__ == "__main__":
    unittest.main()
