#!/usr/bin/env python3


from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import libs_facade_check as lfc


def _modules(src: str) -> list[str]:
    return [m for m, _ in lfc.imported_modules(ast.parse(src))]


def _check_source(src: str, name: str = "_probe.py"):
    tmp = lfc.ADDON_TREES[0] / name
    tmp.write_text(src, encoding="utf-8")
    try:
        return lfc.check(files=[tmp])
    finally:
        tmp.unlink()


class TestSymbolVersusModule(unittest.TestCase):
    def test_area_import_of_a_symbol_passes(self):
        report = _check_source("from odoo.libs.numbers import float_round\n")
        self.assertEqual(report.new, [])
        self.assertTrue(report.ok)

    def test_leaf_module_import_of_the_same_symbol_fails(self):
        report = _check_source(
            "from odoo.libs.numbers.float_utils import float_round\n"
        )
        self.assertEqual(
            [v.module for v in report.new], ["odoo.libs.numbers.float_utils"]
        )
        self.assertFalse(report.ok)

    def test_the_two_are_indistinguishable_by_name_alone(self):
        self.assertTrue(lfc.module_exists("odoo.libs.numbers.float_utils"))
        self.assertFalse(lfc.module_exists("odoo.libs.numbers.float_round"))

    def test_top_level_module_is_itself_an_area(self):
        report = _check_source("from odoo.libs.intervals import Intervals\n")
        self.assertEqual(report.new, [])

    def test_bare_area_import_passes(self):
        self.assertEqual(_check_source("from odoo.libs import OrderedSet\n").new, [])


class TestImportForms(unittest.TestCase):
    def test_plain_import_of_a_leaf_is_caught(self):
        report = _check_source("import odoo.libs.numbers.float_utils\n")
        self.assertEqual(
            [v.module for v in report.new], ["odoo.libs.numbers.float_utils"]
        )

    def test_plain_import_of_an_area_passes(self):
        self.assertEqual(_check_source("import odoo.libs.numbers\n").new, [])

    def test_relative_imports_are_ignored(self):
        self.assertEqual(_modules("from . import models\nfrom ..x import y\n"), [])

    def test_non_libs_imports_are_ignored(self):
        self.assertEqual(
            _modules("from odoo.tools import config\nimport odoo.orm\n"), []
        )


class TestAreas(unittest.TestCase):
    def test_areas_come_from_disk(self):
        found = lfc.areas()
        self.assertIn("odoo.libs", found)
        for area in ("odoo.libs.numbers", "odoo.libs.web", "odoo.libs.xml"):
            with self.subTest(area=area):
                self.assertIn(area, found)

    def test_a_leaf_is_not_an_area(self):
        self.assertNotIn("odoo.libs.numbers.float_utils", lfc.areas())

    def test_every_area_really_exists(self):
        for area in lfc.areas():
            with self.subTest(area=area):
                self.assertTrue(lfc.module_exists(area) or area == "odoo.libs")


class TestPinsAreLive(unittest.TestCase):
    def test_every_known_violation_still_matches(self):
        report = lfc.check()
        pinned = {(k.path, k.module) for k in lfc.KNOWN_VIOLATIONS}
        seen = {(v.path, v.module) for v in report.known}
        self.assertEqual(
            pinned - seen,
            set(),
            "KNOWN_VIOLATIONS entries matching no source line — remove them "
            "(the debt was paid) rather than leaving them to rot",
        )

    def test_known_violation_files_exist(self):
        for k in lfc.KNOWN_VIOLATIONS:
            with self.subTest(path=k.path):
                self.assertTrue((lfc.REPO_ROOT / k.path).is_file(), k.path)

    def test_every_pin_states_a_reason(self):
        for k in lfc.KNOWN_VIOLATIONS:
            with self.subTest(path=k.path):
                self.assertGreater(len(k.reason.strip()), 40)


class TestRealTree(unittest.TestCase):
    def test_the_addon_trees_are_clean(self):
        report = lfc.check()
        self.assertEqual(
            [(v.path, v.lineno, v.module) for v in report.new],
            [],
            "addon code reached past an odoo.libs area — import the area instead",
        )

    def test_it_actually_scanned_something(self):
        report = lfc.check()
        self.assertGreater(report.scanned, 1000, "addon trees not found")

    def test_addon_trees_exist(self):
        for tree in lfc.ADDON_TREES:
            with self.subTest(tree=str(tree)):
                self.assertTrue(tree.is_dir())

    def test_scanned_trees_exist(self):
        for tree in lfc.SCANNED_TREES:
            with self.subTest(tree=str(tree)):
                self.assertTrue(tree.is_dir(), f"{tree} is in SCANNED_TREES but absent")

    def test_every_core_package_is_scanned(self):

        excused = {
            "libs",
            "addons",
        }
        core_root = lfc.REPO_ROOT / "odoo"
        packages = {
            p.name
            for p in core_root.iterdir()
            if p.is_dir() and (p / "__init__.py").exists() and p.name != "__pycache__"
        }
        scanned = {t.name for t in lfc.SCANNED_TREES}
        unscanned = packages - scanned - excused
        self.assertEqual(
            unscanned,
            set(),
            f"core package(s) outside libs_facade_check's scope: {sorted(unscanned)} "
            f"— add to SCANNED_TREES, or excuse here with a reason",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
