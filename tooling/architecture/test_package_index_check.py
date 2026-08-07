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
        on_disk = {
            readme.parent.name
            for readme in pic.CORE_ROOT.rglob("README.md")
            if "addons" not in readme.parts and "_vendor" not in readme.parts
        }
        unclassified = on_disk - set(pic.PACKAGE_INDEXES) - pic.READMES_WITHOUT_AN_INDEX
        self.assertEqual(
            unclassified,
            set(),
            f"core README(s) neither gated nor excused: {sorted(unclassified)} — "
            f"add to PACKAGE_INDEXES with its inventory heading, or to "
            f"READMES_WITHOUT_AN_INDEX if it carries no module list",
        )

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
