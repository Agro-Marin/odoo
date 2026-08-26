from __future__ import annotations

import textwrap
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

import package_index_check as pic


def make_package(root: Path, name: str, modules: list[str], readme: str) -> Path:
    core = root / "core"
    pkg = core / name
    pkg.mkdir(parents=True, exist_ok=True)
    for module in modules:
        (pkg / module).touch()
    (pkg / "README.md").write_text(textwrap.dedent(readme).strip() + "\n", "utf-8")
    return core


INDEX = {"pkg": ("README.md", "## Module map")}

_NOT_CORE = ("addons", "_vendor")


def core_readme_packages(core_root: Path) -> set[str]:

    found = set()
    for readme in core_root.rglob("README.md"):
        rel = readme.relative_to(core_root).parts
        if set(rel) & set(_NOT_CORE):
            continue
        if len(rel) < 2:
            continue
        found.add(rel[-2])
    return found


class ExtractSectionTest(unittest.TestCase):
    def test_stops_at_the_next_heading_of_the_same_level(self):
        section = pic.extract_section(
            "## Module map\n| `a.py` | x |\n\n## Other\n| `b.py` | y |\n",
            "## Module map",
        )
        self.assertEqual(pic.listed_modules(section), {"a"})

    def test_keeps_deeper_subheadings(self):
        section = pic.extract_section(
            "## Patch Index\n### Stdlib\n| `a.py` | x |\n### Core\n| `b.py` | y |\n"
            "## Patch Types\n| `c.py` | z |\n",
            "## Patch Index",
        )
        self.assertEqual(pic.listed_modules(section), {"a", "b"})

    def test_stops_at_a_higher_level_heading(self):
        section = pic.extract_section(
            "## Module map\n| `a.py` | x |\n# Appendix\n| `b.py` | y |\n",
            "## Module map",
        )
        self.assertEqual(pic.listed_modules(section), {"a"})

    def test_a_missing_heading_raises_rather_than_reporting_empty(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            pic.extract_section("# Title\n\nno index here\n", "## Module map")


class ListedModulesTest(unittest.TestCase):
    def test_a_row_is_recognised(self):
        self.assertEqual(
            pic.listed_modules(["| `cursor.py` | the cr object | no |"]), {"cursor"}
        )

    def test_a_backticked_module_in_prose_is_not_an_entry(self):
        self.assertEqual(
            pic.listed_modules(
                ["See `pool.py` for the borrow path.", "Also `dsn.py`."]
            ),
            set(),
        )

    def test_a_leading_underscore_module_is_recognised(self):
        self.assertEqual(
            pic.listed_modules(["| `_excel_utils.py` | shared | UTIL |"]),
            {"_excel_utils"},
        )

    def test_a_non_python_row_is_ignored(self):
        self.assertEqual(pic.listed_modules(["| `README.md` | this file |"]), set())


class DriftTest(unittest.TestCase):
    def test_a_module_absent_from_the_index_fails(self):
        with TemporaryDirectory() as tmp:
            core = make_package(
                Path(tmp),
                "pkg",
                ["a.py", "b.py"],
                "## Module map\n| `a.py` | only a |\n",
            )
            report = pic.check(core, INDEX)
            self.assertEqual(report.packages[0].missing, ["b"])
            self.assertFalse(report.ok)

    def test_an_index_entry_with_no_module_fails(self):
        with TemporaryDirectory() as tmp:
            core = make_package(
                Path(tmp),
                "pkg",
                ["a.py"],
                "## Module map\n| `a.py` | a |\n| `gone.py` | deleted |\n",
            )
            report = pic.check(core, INDEX)
            self.assertEqual(report.packages[0].phantom, ["gone"])

    def test_init_may_be_listed_but_is_not_required(self):
        with TemporaryDirectory() as tmp:
            core = make_package(
                Path(tmp),
                "pkg",
                ["__init__.py", "a.py"],
                "## Module map\n| `a.py` | a |\n",
            )
            self.assertTrue(pic.check(core, INDEX).ok)

    def test_listing_init_is_also_accepted(self):
        with TemporaryDirectory() as tmp:
            core = make_package(
                Path(tmp),
                "pkg",
                ["__init__.py", "a.py"],
                "## Module map\n| `__init__.py` | api |\n| `a.py` | a |\n",
            )
            self.assertTrue(pic.check(core, INDEX).ok)

    def test_a_complete_index_passes(self):
        with TemporaryDirectory() as tmp:
            core = make_package(
                Path(tmp),
                "pkg",
                ["a.py", "b.py"],
                "## Module map\n| `a.py` | a |\n| `b.py` | b |\n",
            )
            self.assertTrue(pic.check(core, INDEX).ok)


class SelfCountsTest(unittest.TestCase):
    COUNTS = {r"\*\*Total\*\*: (\d+) files": "files"}

    def _pkg(self, tmp, stated_line, modules=("a.py", "b.py")):
        return make_package(
            Path(tmp), "pkg", list(modules), f"## Module map\n{stated_line}\n"
        )

    def test_a_correct_self_count_passes(self):
        with TemporaryDirectory() as tmp:
            core = self._pkg(
                tmp, "| `a.py` | a |\n| `b.py` | b |\n\n**Total**: 2 files"
            )
            with unittest.mock.patch.dict(pic.SELF_COUNTS, {"pkg": self.COUNTS}):
                report = pic.check(core, INDEX)
            self.assertEqual(report.packages[0].wrong_counts, [])
            self.assertTrue(report.packages[0].ok)

    def test_a_wrong_self_count_fails(self):
        with TemporaryDirectory() as tmp:
            core = self._pkg(
                tmp, "| `a.py` | a |\n| `b.py` | b |\n\n**Total**: 99 files"
            )
            with unittest.mock.patch.dict(pic.SELF_COUNTS, {"pkg": self.COUNTS}):
                report = pic.check(core, INDEX)
            self.assertEqual(report.packages[0].wrong_counts, [("files", 99, 2)])
            self.assertFalse(report.packages[0].ok)

    def test_a_registered_pattern_that_matches_nothing_raises(self):

        with TemporaryDirectory() as tmp:
            core = self._pkg(
                tmp, "| `a.py` | a |\n| `b.py` | b |\n\n**Total:** 99 files"
            )
            with unittest.mock.patch.dict(pic.SELF_COUNTS, {"pkg": self.COUNTS}):
                with self.assertRaisesRegex(ValueError, "matched nothing"):
                    pic.check(core, INDEX)

    def test_init_is_excluded_from_the_measured_count(self):
        with TemporaryDirectory() as tmp:
            core = self._pkg(
                tmp,
                "| `a.py` | a |\n| `b.py` | b |\n\n**Total**: 2 files",
                modules=("a.py", "b.py", "__init__.py"),
            )
            with unittest.mock.patch.dict(pic.SELF_COUNTS, {"pkg": self.COUNTS}):
                self.assertTrue(pic.check(core, INDEX).ok)

    def test_patches_kind_skips_leading_underscore_helpers(self):
        pkg = pic.CORE_ROOT / "_monkeypatches"
        files = pic._measure("files", pkg)
        patches = pic._measure("patches", pkg)
        self.assertGreater(files, patches, "no helper modules distinguished")

    def test_the_live_patterns_still_match_their_readme(self):

        for package, counts in pic.SELF_COUNTS.items():
            readme_name, _heading = pic.PACKAGE_INDEXES[package]
            text = (pic.CORE_ROOT / package / readme_name).read_text(encoding="utf-8")
            for pattern in counts:
                with self.subTest(package=package, pattern=pattern):
                    self.assertRegex(text, pattern)


class LiveRepositoryTest(unittest.TestCase):
    def test_the_committed_indexes_are_clean(self):
        report = pic.check()
        for pkg in report.packages:
            self.assertEqual(pkg.missing, [], f"{pkg.package}: modules not indexed")
            self.assertEqual(pkg.phantom, [], f"{pkg.package}: indexed but absent")

    def test_every_registered_package_is_actually_covered(self):

        report = pic.check()
        by_name = {p.package: p for p in report.packages}
        self.assertEqual(
            set(by_name),
            set(pic.PACKAGE_INDEXES),
            "check() did not report every package registered in PACKAGE_INDEXES",
        )
        for name, pkg in by_name.items():
            self.assertGreater(
                len(pkg.listed),
                1,
                f"{name}: parsed {len(pkg.listed)} inventory rows -- the section "
                "heading probably stopped matching, which would make the "
                "missing/phantom assertions vacuous",
            )

    def test_every_core_readme_is_classified(self):

        on_disk = core_readme_packages(pic.CORE_ROOT)
        self.assertTrue(on_disk, "no core READMEs found at all — the walk broke")
        unclassified = on_disk - set(pic.PACKAGE_INDEXES) - pic.READMES_WITHOUT_AN_INDEX
        self.assertEqual(
            unclassified,
            set(),
            f"core README(s) neither gated nor excused: {sorted(unclassified)} — "
            f"add to PACKAGE_INDEXES with its inventory heading, or to "
            f"READMES_WITHOUT_AN_INDEX if it carries no module list",
        )

    def test_the_completeness_guard_survives_a_nested_checkout(self):

        with TemporaryDirectory() as tmp:
            core = Path(tmp) / "addons" / "odoo" / "odoo"
            for pkg in ("db", "http"):
                (core / pkg).mkdir(parents=True)
                (core / pkg / "README.md").write_text("## Module map\n", "utf-8")
            (core / "addons" / "base").mkdir(parents=True)
            (core / "addons" / "base" / "README.md").write_text("x\n", "utf-8")
            (core / "_vendor").mkdir()
            (core / "_vendor" / "README.md").write_text("x\n", "utf-8")

            found = core_readme_packages(core)
            self.assertEqual(found, {"db", "http"})
            self.assertNotIn("base", found, "the addons tree must still be skipped")
            self.assertNotIn("_vendor", found)

    def test_the_two_classifications_do_not_overlap(self):
        overlap = set(pic.PACKAGE_INDEXES) & pic.READMES_WITHOUT_AN_INDEX
        self.assertEqual(overlap, set(), f"both gated and excused: {sorted(overlap)}")

    def test_section_scoping_is_load_bearing(self):
        pkg = pic.CORE_ROOT / "_monkeypatches"
        text = (pkg / "README.md").read_text(encoding="utf-8")
        actual = pic.actual_modules(pkg)

        unscoped = pic.listed_modules(text.splitlines())
        scoped = pic.listed_modules(pic.extract_section(text, "## Patch Index"))

        self.assertEqual(
            sorted(scoped - actual),
            [],
            "the Patch Index names a module that does not exist",
        )
        self.assertTrue(
            scoped < unscoped,
            "the Patch Index and the whole file now read the same, so scoping "
            "changes nothing here and this live check proves nothing — point it "
            "at a README that still discusses non-modules, or retire it. The "
            "extract_section unit tests above keep covering the mechanism.",
        )
        self.assertTrue(
            unscoped - actual,
            "every name in the README is now a real module, so an unscoped read "
            "would be just as correct — same verdict as above.",
        )

    def test_row_regex_agrees_with_actual_modules(self):

        for stem in (
            "18.1-00-sql-constraint",
            "17.5-01-tree-to-list",
            "18.5-00-deprecated-properties",
        ):
            with self.subTest(stem=stem):
                row = f"| `{stem}.py` | tested | 0 | note |"
                self.assertEqual(pic.listed_modules([row]), {stem})

    def test_row_regex_still_rejects_a_path(self):

        self.assertEqual(pic.listed_modules(["| `db/cursor.py` | x |"]), set())
        self.assertEqual(pic.listed_modules(["| `odoo/http/stream.py` | x |"]), set())

    def test_upgrade_code_inventory_is_actually_enforced(self):

        pkg = pic.CORE_ROOT / "upgrade_code"
        readme, heading = pic.PACKAGE_INDEXES["upgrade_code"]
        section = pic.extract_section(
            (pkg / readme).read_text(encoding="utf-8"), heading
        )
        listed = pic.listed_modules(section)
        self.assertIn("18.1-00-sql-constraint", listed)
        self.assertEqual(listed, pic.actual_modules(pkg))
        pretend = pic.actual_modules(pkg) | {"19.0-00-something-new"}
        self.assertEqual(sorted(pretend - listed), ["19.0-00-something-new"])

    def test_a_module_added_to_db_would_be_caught(self):
        report = pic.check()
        db = next(p for p in report.packages if p.package == "db")
        self.assertNotIn("_probe", db.listed)
        missing = sorted((db.actual | {"_probe"}) - db.listed - pic.OPTIONAL_MODULES)
        self.assertEqual(missing, ["_probe"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
