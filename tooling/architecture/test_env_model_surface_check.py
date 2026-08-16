#!/usr/bin/env python3


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
            'x = config["db_name"]\n'
            "y = self.env[model_var]\n"
            'z = env["nodot"]\n'
            'w = data["a.b.c"]\n'
        )
        self.assertEqual(hits, [])

    def test_base_is_recognised(self):
        self.assertEqual({m for m, _ in _collect('env["base"]')}, {"base"})

    def test_dynamic_key_is_not_matched(self):
        self.assertEqual(_collect("env[model_name]"), [])


class TestDriftDetection(unittest.TestCase):
    def _report_over(self, models):
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
        subset = sorted(emsc.KNOWN_MODEL_SURFACE)[:-1]
        report = self._report_over(subset)
        self.assertEqual(len(report.removed), 1)
        self.assertFalse(report.ok)

    def test_exact_match_is_ok(self):
        report = self._report_over(sorted(emsc.KNOWN_MODEL_SURFACE))
        self.assertTrue(report.ok)
        self.assertFalse(report.added)
        self.assertFalse(report.removed)


class TestForbiddenReachers(unittest.TestCase):
    def _report_from(self, path: str, model: str = "ir.model"):
        report = emsc.Report(reaches=[emsc.Reach(model, path, 1)])
        report.added = report.models - emsc.KNOWN_MODEL_SURFACE
        report.removed = set()
        report.forbidden = [
            r
            for r in report.reaches
            if r.path.startswith(
                tuple(f"{s}/" for s in emsc.SUBTREES_WITH_NO_MODEL_REACH)
            )
        ]
        return report

    def test_a_pure_subtree_reaching_a_known_model_fails(self):
        report = self._report_from("odoo/orm/components/model_graph.py")
        self.assertFalse(report.added, "the model is known -- that is the point")
        self.assertTrue(report.forbidden)
        self.assertFalse(report.ok)

    def test_an_ordinary_subtree_reaching_a_known_model_is_fine(self):
        report = self._report_from("odoo/orm/models/mixins/read.py")
        self.assertFalse(report.forbidden)
        self.assertTrue(report.ok)

    def test_a_prefix_is_not_matched_by_a_sibling_with_the_same_start(self):
        report = self._report_from("odoo/dbx/thing.py")
        self.assertFalse(report.forbidden)

    def test_every_pinned_subtree_exists_and_is_currently_clean(self):
        live = emsc.check()
        reached_paths = {r.path for r in live.reaches}
        for subtree in emsc.SUBTREES_WITH_NO_MODEL_REACH:
            self.assertTrue(
                (emsc.REPO_ROOT / subtree).is_dir(),
                f"{subtree} is pinned at zero model reaches but does not exist",
            )
            offenders = sorted(p for p in reached_paths if p.startswith(f"{subtree}/"))
            self.assertEqual(
                offenders,
                [],
                f"{subtree} is pinned at zero but reaches models: {offenders}",
            )


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
        for name in (*emsc.SCOPE_PACKAGES, *emsc.SCOPE_EXEMPT_PACKAGES):
            with self.subTest(package=name):
                self.assertTrue(
                    (emsc.CORE / name).is_dir(), f"{name} is listed but absent"
                )

    def test_the_two_lists_do_not_overlap(self):
        overlap = set(emsc.SCOPE_PACKAGES) & emsc.SCOPE_EXEMPT_PACKAGES
        self.assertEqual(overlap, set(), f"both scanned and exempt: {sorted(overlap)}")


class TestTheAccessorChannel(unittest.TestCase):
    def test_an_accessor_reach_is_collected(self):
        hits = _collect("x = self.env.user.name")
        self.assertEqual([m for m, _ in hits], ["res.users"])

    def test_a_bare_env_accessor_reach_is_collected(self):
        self.assertEqual([m for m, _ in _collect("y = env.company")], ["res.company"])

    def test_the_same_attribute_on_a_non_env_object_is_ignored(self):
        for src in ("a = record.user", "b = config.lang", "c = self.company"):
            with self.subTest(src=src):
                self.assertEqual(_collect(src), [])

    def test_the_accessor_map_covers_environment(self):

        source = (emsc.CORE / "orm" / "runtime" / "environment.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        looked_up = {
            node.slice.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
            and emsc._MODEL_RE.match(node.slice.value)
        }
        declared = (
            set(emsc.ENV_MODEL_ACCESSORS.values()) | emsc.ENV_INTERNAL_MODEL_LOOKUPS
        )
        uncovered = looked_up - declared
        self.assertEqual(
            uncovered,
            set(),
            f"environment.py reaches {sorted(uncovered)} through an undeclared "
            f"member — consumers of it would be invisible to this gate. Add it to "
            f"ENV_MODEL_ACCESSORS if the member returns that model to its caller, "
            f"or to ENV_INTERNAL_MODEL_LOOKUPS if it only consults it.",
        )

    def test_the_two_declarations_do_not_overlap(self):
        overlap = (
            set(emsc.ENV_MODEL_ACCESSORS.values()) & emsc.ENV_INTERNAL_MODEL_LOOKUPS
        )
        self.assertEqual(overlap, set(), f"declared both ways: {sorted(overlap)}")


if __name__ == "__main__":
    unittest.main()
