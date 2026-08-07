"""Self-test for ``package_index_check.py``.

The gate's failure mode is the same as any documentation checker's: parse the
README slightly wrong and it reports a clean inventory of almost nothing. So the
tests concentrate on the parse — above all on **section scoping**, which is not
a nicety here but the difference between a working gate and one that fires six
times against a correct document (`_monkeypatches/README.md`'s *Recently
Removed* table names six modules that are supposed to be gone).
"""

from __future__ import annotations

import textwrap
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

import package_index_check as pic


def make_package(root: Path, name: str, modules: list[str], readme: str) -> Path:
    """Build a package with *modules* and a README, and return the core root."""
    core = root / "core"
    pkg = core / name
    pkg.mkdir(parents=True, exist_ok=True)
    for module in modules:
        (pkg / module).touch()
    (pkg / "README.md").write_text(textwrap.dedent(readme).strip() + "\n", "utf-8")
    return core


INDEX = {"pkg": ("README.md", "## Module map")}

#: Trees inside the core that carry READMEs this gate does not own.
_NOT_CORE = ("addons", "_vendor")


def core_readme_packages(core_root: Path) -> set[str]:
    """Packages under ``core_root`` that ship a README.

    Filters on the path RELATIVE to ``core_root``. Filtering the absolute path
    is what made ``test_every_core_readme_is_classified`` vacuous in a
    ``<ws>/addons/odoo`` checkout: every path contains ``addons`` there, so the
    exclusion swallowed the whole tree.
    """
    found = set()
    for readme in core_root.rglob("README.md"):
        rel = readme.relative_to(core_root).parts
        if set(rel) & set(_NOT_CORE):
            continue
        if len(rel) < 2:  # a README at the core root belongs to no package
            continue
        found.add(rel[-2])
    return found


class ExtractSectionTest(unittest.TestCase):
    """Only the inventory section counts."""

    def test_stops_at_the_next_heading_of_the_same_level(self):
        section = pic.extract_section(
            "## Module map\n| `a.py` | x |\n\n## Other\n| `b.py` | y |\n",
            "## Module map",
        )
        self.assertEqual(pic.listed_modules(section), {"a"})

    def test_keeps_deeper_subheadings(self):
        """The patch index is split across several ``###`` subsections."""
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
    """Which text counts as an inventory entry."""

    def test_a_row_is_recognised(self):
        self.assertEqual(
            pic.listed_modules(["| `cursor.py` | the cr object | no |"]), {"cursor"}
        )

    def test_a_backticked_module_in_prose_is_not_an_entry(self):
        """Only a row *starts* an entry; prose mentions must not count, or the
        index would appear to list modules it merely discusses."""
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
    """Both directions of the symmetric rule."""

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
    """A README that restates a count about itself must restate it correctly.

    This whole feature had no test. It also failed open: an unmatched pattern
    was skipped, so rewording ``**Total**: 15 files`` to ``**Total:** 15 files``
    silently retired the check while the number stayed wrong.
    """

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
        """The fail-open regression, pinned.

        Reword the label and the count check used to vanish, leaving the number
        wrong and the gate green.
        """
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
        """The registered patterns are claims about a real file; check them.

        Without this, the ValueError above only fires when someone happens to
        run the gate — which is the same "nobody looked" failure one level up.
        """
        for package, counts in pic.SELF_COUNTS.items():
            readme_name, _heading = pic.PACKAGE_INDEXES[package]
            text = (pic.CORE_ROOT / package / readme_name).read_text(encoding="utf-8")
            for pattern in counts:
                with self.subTest(package=package, pattern=pattern):
                    self.assertRegex(text, pattern)


class LiveRepositoryTest(unittest.TestCase):
    """Against the real READMEs, plus proof the gate would notice."""

    def test_the_committed_indexes_are_clean(self):
        report = pic.check()
        for pkg in report.packages:
            self.assertEqual(pkg.missing, [], f"{pkg.package}: modules not indexed")
            self.assertEqual(pkg.phantom, [], f"{pkg.package}: indexed but absent")

    def test_every_registered_package_is_actually_covered(self):
        """If the parse silently broke, `listed` would shrink and every
        assertion above would pass vacuously.

        Derived from ``PACKAGE_INDEXES`` rather than hardcoded: this used to
        assert the set was exactly ``{db, _monkeypatches}`` and named a minimum
        row count per package, so registering a third package (``http``) turned
        a *correct* extension of the gate's coverage into a red build. A
        coverage test that fails when coverage grows is pushing the wrong way.

        The vacuity guard it existed for is kept, and made general: every
        registered package must be reported, and every reported package must
        have parsed a non-trivial inventory rather than an empty one.
        """
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
        """A new package README must be gated or explicitly excused.

        ``test_every_registered_package_is_actually_covered`` pins the reported set
        to ``PACKAGE_INDEXES``, which guards against the parse silently
        breaking — but it is not a *completeness* guard: it passes just as
        happily when a third README appears carrying an un-gated module
        inventory, because ``PACKAGE_INDEXES`` is an inclusion list and a
        package outside it cannot fail.

        That is the same shape as ``layer_check``'s
        ``test_core_source_covers_every_core_package``,
        ``libs_facade_check``'s ``test_every_core_package_is_scanned`` and
        ``env_model_surface_check``'s ``test_every_core_package_is_scoped_or_exempt``:
        where a gate's coverage is a hand-maintained list, the list is the part
        that rots.
        """
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
        """The filter used to read the ABSOLUTE path.

        ``_repo_root`` supports two shapes, ``<ws>/odoo`` and the historical
        ``<ws>/addons/odoo``, and ``test_repo_root`` pins both. Under the second
        one every path contains an ``addons`` component, so ``"addons" not in
        readme.parts`` excluded **every** README, ``on_disk`` came out empty,
        and this guard passed while checking nothing — including for a
        brand-new un-gated README carrying a module inventory.
        """
        with TemporaryDirectory() as tmp:
            core = Path(tmp) / "addons" / "odoo" / "odoo"
            for pkg in ("db", "http"):
                (core / pkg).mkdir(parents=True)
                (core / pkg / "README.md").write_text("## Module map\n", "utf-8")
            # the addon tree that the filter is actually meant to skip
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
        """The regression this gate would otherwise ship.

        `_monkeypatches/README.md` has a *Recently Removed* table naming six
        modules that are correctly absent from the tree. Scanning the whole
        file instead of the Patch Index section reports all six as phantoms —
        six failures against a document that is exactly right.
        """
        pkg = pic.CORE_ROOT / "_monkeypatches"
        text = (pkg / "README.md").read_text(encoding="utf-8")
        actual = pic.actual_modules(pkg)

        unscoped = pic.listed_modules(text.splitlines())
        scoped = pic.listed_modules(pic.extract_section(text, "## Patch Index"))

        self.assertEqual(sorted(scoped - actual), [])
        self.assertEqual(
            sorted(unscoped - actual),
            ["lxml", "pytz", "urllib3", "xlrd", "xlwt", "zeep"],
        )

    def test_row_regex_agrees_with_actual_modules(self):
        """The two halves must accept the same idea of a module name.

        `actual_modules()` reports ``p.stem`` for every ``*.py``, i.e. any
        filename. `_ROW_RE` used to require an importable identifier
        (``[A-Za-z_][A-Za-z0-9_]*``), which cannot match a dated rewrite script:
        ``18.1-00-sql-constraint`` starts with a digit and contains dots and
        hyphens.

        The failure that would have caused is the silent kind. A README for
        ``odoo/upgrade_code/`` would have parsed to an inventory of **nothing**,
        matched every module as "missing", and — had the package not been
        registered — enforced nothing at all while looking exactly like the
        gated ones. That is the same shape this checker exists to prevent one
        level up.
        """
        for stem in (
            "18.1-00-sql-constraint",
            "17.5-01-tree-to-list",
            "18.5-00-deprecated-properties",
        ):
            with self.subTest(stem=stem):
                row = f"| `{stem}.py` | tested | 0 | note |"
                self.assertEqual(pic.listed_modules([row]), {stem})

    def test_row_regex_still_rejects_a_path(self):
        """Widening the charset must not let a backticked path in.

        An inventory names modules; ``| `db/cursor.py` |`` is a citation. If it
        parsed as the module ``db/cursor`` it would be reported as a phantom
        against a README that is merely quoting a path.
        """
        self.assertEqual(pic.listed_modules(["| `db/cursor.py` | x |"]), set())
        self.assertEqual(pic.listed_modules(["| `odoo/http/stream.py` | x |"]), set())

    def test_upgrade_code_inventory_is_actually_enforced(self):
        """The registration has to bite, not merely exist.

        Pretend the package grew a script the README does not list.
        """
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
        """Mutation: pretend odoo/db/ grew a module the README does not list."""
        report = pic.check()
        db = next(p for p in report.packages if p.package == "db")
        self.assertNotIn("_probe", db.listed)
        # Simulate the tree gaining it, without touching the real tree.
        missing = sorted((db.actual | {"_probe"}) - db.listed - pic.OPTIONAL_MODULES)
        self.assertEqual(missing, ["_probe"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
