"""Self-test for ``subsystem_map_check.py``.

The checker's whole value is that it fails when the map drifts.  A checker that
parses the map *loosely* fails that job in the quietest possible way: it reports
clean over text it never understood.  These tests are therefore weighted towards
the ways this particular parser could lie —

* reading a wrapped prose **description** as a list of modules (the first
  version did exactly this: ``service/``'s three continuation lines became
  thirteen non-existent modules of ``odoo/``),
* splitting a parenthetical gloss on a comma *inside* it,
* silently finding no map at all and reporting success,
* checking only one kind of child, so a missing subpackage hides behind a
  complete module list.

Every synthetic case builds a real temporary tree, so the assertions are about
the gate end-to-end rather than about the parser agreeing with itself.  The last
class runs it against the live repository.
"""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import subsystem_map_check as smc


def write_map(root: Path, body: str) -> Path:
    """Write an ARCHITECTURE.md whose subsystem map is *body*."""
    md = root / "ARCHITECTURE.md"
    md.write_text(
        "# Title\n\nprose\n\n## Subsystem map\n\n```\n"
        + textwrap.dedent(body).strip("\n")
        + "\n```\n\ntrailing prose\n",
        encoding="utf-8",
    )
    return md


def make_tree(root: Path, spec: dict[str, list[str]]) -> Path:
    """Build a package tree: ``{"pkg": ["mod.py", "sub/"]}`` under ``core/``."""
    core = root / "core"
    core.mkdir(exist_ok=True)
    (core / "__init__.py").touch()
    for package, children in spec.items():
        base = core / package if package else core
        base.mkdir(parents=True, exist_ok=True)
        (base / "__init__.py").touch()
        for child in children:
            if child.endswith("/"):
                sub = base / child.rstrip("/")
                sub.mkdir(exist_ok=True)
                (sub / "__init__.py").touch()
            else:
                (base / child).touch()
    return core


class ParseNamesTest(unittest.TestCase):
    """The name-list / description boundary — the parser's only hard decision."""

    def test_a_bare_list_is_all_names(self):
        names, complete = smc.parse_names("pool, cursor, ddl")
        self.assertEqual([n for n, _ in names], ["pool", "cursor", "ddl"])
        self.assertTrue(complete)

    def test_a_description_stops_the_list_after_its_subject(self):
        """``service/  Process lifecycle + servers: server, _base_server``.

        The subject (``service/``) is a name; everything after it is prose. The
        regression this pins is real: reading on produced ``odoo/server.py``,
        ``odoo/_base_server.py``, ``odoo/_threaded.py`` … none of which exist.
        """
        names, complete = smc.parse_names(
            "service/        Process lifecycle + servers: server, _base_server,"
        )
        self.assertEqual(names, [("service", True)])
        self.assertFalse(complete)

    def test_one_space_between_name_and_prose_still_stops(self):
        """``_monkeypatches/ Explicit, import-hook-driven …`` — a column-width
        rule would read ``Explicit`` as part of the name."""
        names, complete = smc.parse_names(
            "_monkeypatches/ Explicit, import-hook-driven third-party patches"
        )
        self.assertEqual(names, [("_monkeypatches", True)])
        self.assertFalse(complete)

    def test_a_gloss_annotates_a_name_rather_than_ending_the_list(self):
        names, complete = smc.parse_names("models/  (BaseModel + 21 mixins)  (Layer 2)")
        self.assertEqual(names, [("models", True)])
        self.assertTrue(complete)

    def test_a_comma_inside_a_gloss_does_not_split(self):
        names, _ = smc.parse_names(
            "lag (replica apply-lag ceiling, db_replica_max_lag)"
        )
        self.assertEqual(names, [("lag", False)])

    def test_nested_parentheses_in_a_gloss(self):
        names, complete = smc.parse_names(
            "_params (annotation-driven @route(typed=True) coercion), geoip"
        )
        self.assertEqual([n for n, _ in names], ["_params", "geoip"])
        self.assertTrue(complete)

    def test_middot_separates_names(self):
        names, _ = smc.parse_names("metrics (SQL per cursor) · stats (what it did)")
        self.assertEqual([n for n, _ in names], ["metrics", "stats"])

    def test_a_name_at_the_prose_boundary_is_still_taken(self):
        """``api/ · fields/ · models/   Thin public re-export shims`` — all
        three are names; only the trailing text is prose."""
        names, complete = smc.parse_names(
            "api/ · fields/ · models/   Thin public re-export shims over orm/"
        )
        self.assertEqual([n for n, _ in names], ["api", "fields", "models"])
        self.assertFalse(complete)

    def test_trailing_comma_does_not_produce_an_empty_name(self):
        names, complete = smc.parse_names("pool, cursor,")
        self.assertEqual([n for n, _ in names], ["pool", "cursor"])
        self.assertTrue(complete)


class DatedModuleStemTest(unittest.TestCase):
    """The name charset must accept whatever ``_actual_children`` reports.

    That function returns ``p.stem`` for every ``*.py`` — any filename, not just
    an importable identifier. ``[A-Za-z_][A-Za-z0-9_]*`` could not match a dated
    rewrite script (``18.1-00-sql-constraint.py``: leading digit, dots,
    hyphens), and ``package_index_check._ROW_RE`` had to be widened for exactly
    this. The failure would be silent-then-loud: the parser reads none of
    ``upgrade_code/``'s nine scripts, and rule 2 reports all nine as
    undocumented against a map that lists every one.
    """

    STEMS = (
        "18.1-00-sql-constraint",
        "17.5-01-tree-to-list",
        "18.5-00-deprecated-properties",
    )

    def test_a_dated_stem_parses_as_one_name(self):
        for stem in self.STEMS:
            with self.subTest(stem=stem):
                self.assertEqual(smc.parse_names(stem), ([(stem, False)], True))

    def test_a_list_of_dated_stems_parses(self):
        names, complete = smc.parse_names(", ".join(self.STEMS))
        self.assertEqual([n for n, _ in names], list(self.STEMS))
        self.assertTrue(complete)

    def test_the_charset_agrees_with_what_the_tree_reports(self):
        """Every real ``upgrade_code`` stem must be expressible in the map."""
        modules, _packages = smc._actual_children("upgrade_code", smc.CORE_ROOT)
        self.assertTrue(modules, "upgrade_code has no modules — probe is vacuous")
        for stem in sorted(modules):
            with self.subTest(stem=stem):
                self.assertEqual(smc.parse_names(stem), ([(stem, False)], True))

    def test_widening_did_not_break_the_prose_boundary(self):
        # The first attempt anchored the name to a delimiter, which dropped the
        # leading token of every package line.
        self.assertEqual(
            smc.parse_names("service/  Process lifecycle + servers: server"),
            ([("service", True)], False),
        )
        names, complete = smc.parse_names(
            "api/ · fields/ · models/   Thin public re-export shims"
        )
        self.assertEqual([n for n, _ in names], ["api", "fields", "models"])
        self.assertFalse(complete)


class ExtractMapBlockTest(unittest.TestCase):
    """A map that cannot be found must be an error, never a clean report."""

    def test_missing_heading_raises(self):
        with self.assertRaisesRegex(ValueError, "no '## Subsystem map'"):
            smc.extract_map_block("# Title\n\nno map here\n")

    def test_heading_without_a_fence_raises(self):
        with self.assertRaisesRegex(ValueError, "no fenced block"):
            smc.extract_map_block("## Subsystem map\n\njust prose\n")

    def test_unterminated_fence_raises(self):
        with self.assertRaisesRegex(ValueError, "unterminated fence"):
            smc.extract_map_block("## Subsystem map\n\n```\nodoo/\n")

    def test_line_numbers_are_one_based_and_point_at_the_entry(self):
        block, first = smc.extract_map_block(
            "## Subsystem map\n\n```\nodoo/\n├── orm/\n```\n"
        )
        self.assertEqual(block, ["odoo/", "├── orm/"])
        # "```" is line 3, so the first block line is line 4.
        self.assertEqual(first, 4)


class FictionalPathTest(unittest.TestCase):
    """Rule 1 — every path named by the map must exist."""

    def test_a_grouping_drawn_as_a_directory_is_reported(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = make_tree(root, {"db": ["pool.py", "cursor.py"]})
            md = write_map(
                root,
                """
                odoo/
                └── db/             Connectivity
                    └── resilience  breaker
                """,
            )
            report = smc.check(md, core)
            self.assertFalse(report.ok)
            self.assertTrue(
                any("resilience" in name for name, _ in report.fictional),
                report.fictional,
            )

    def test_the_same_grouping_in_brackets_is_accepted(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = make_tree(root, {"db": ["pool.py", "cursor.py"]})
            md = write_map(
                root,
                """
                odoo/
                └── db/             Connectivity
                    └── [resilience] pool, cursor
                """,
            )
            report = smc.check(md, core)
            self.assertEqual(report.fictional, [])
            self.assertTrue(report.ok, report.undocumented)

    def test_a_missing_module_is_reported(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = make_tree(root, {"db": ["pool.py"]})
            md = write_map(
                root,
                """
                odoo/
                └── db/     Connectivity
                    └── pool, cursor
                """,
            )
            report = smc.check(md, core)
            self.assertTrue(any("cursor" in n for n, _ in report.fictional))


class EnumerationCompletenessTest(unittest.TestCase):
    """Rule 2 — an enumeration that starts must finish, per kind."""

    def test_a_missing_module_from_an_enumerated_package_fails(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = make_tree(root, {"db": ["pool.py", "cursor.py", "ddl.py"]})
            md = write_map(
                root,
                """
                odoo/
                └── db/     Connectivity
                    └── pool, cursor
                """,
            )
            report = smc.check(md, core)
            self.assertIn(("db", "ddl.py"), report.undocumented)

    def test_a_missing_subpackage_is_not_hidden_by_a_complete_module_list(self):
        """The per-kind split: modules complete, subpackages not."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = make_tree(root, {"tools": ["misc.py", "assets/", "pdf/"]})
            md = write_map(
                root,
                """
                odoo/
                └── tools/  Utilities
                    ├── misc
                    └── assets/
                """,
            )
            report = smc.check(md, core)
            self.assertIn(("tools", "pdf/"), report.undocumented)

    def test_listing_only_subpackages_does_not_demand_the_modules(self):
        """``tools/`` names ``assets/`` but not its 35 modules — by design."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = make_tree(root, {"tools": ["misc.py", "sql.py", "assets/"]})
            md = write_map(
                root,
                """
                odoo/
                └── tools/  Utilities
                    └── assets/
                """,
            )
            report = smc.check(md, core)
            self.assertEqual(report.undocumented, [])
            self.assertTrue(report.ok)

    def test_a_package_the_map_only_summarises_is_not_enumerated(self):
        """``libs/`` is one line and 138 files; that must stay legal."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = make_tree(root, {"libs": ["a.py", "b.py", "sub/"]})
            md = write_map(
                root,
                """
                odoo/
                └── libs/   Odoo-AGNOSTIC utilities
                """,
            )
            report = smc.check(md, core)
            self.assertTrue(report.ok, (report.fictional, report.undocumented))

    def test_init_pycache_and_tests_are_exempt(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = make_tree(root, {"db": ["pool.py", "tests/"]})
            (core / "db" / "__pycache__").mkdir()
            md = write_map(
                root,
                """
                odoo/
                └── db/     Connectivity
                    └── pool
                """,
            )
            report = smc.check(md, core)
            self.assertTrue(report.ok, (report.fictional, report.undocumented))


class ContinuationLineTest(unittest.TestCase):
    """Wrapped lines: names continue, descriptions do not."""

    def test_a_wrapped_name_list_continues(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = make_tree(root, {"db": ["pool.py", "cursor.py", "ddl.py"]})
            md = write_map(
                root,
                """
                odoo/
                └── db/     Connectivity
                    └── [connectivity] pool, cursor,
                                       ddl
                """,
            )
            report = smc.check(md, core)
            self.assertTrue(report.ok, (report.fictional, report.undocumented))

    def test_a_wrapped_description_contributes_no_names(self):
        """The bug this gate shipped with, pinned.

        ``service/``'s description wraps over three lines naming a dozen
        modules. They are prose. Reading them as names invented a dozen
        top-level modules of ``odoo/`` that do not exist.
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = make_tree(root, {"service": ["server.py"]})
            md = write_map(
                root,
                """
                odoo/
                └── service/    Process lifecycle + servers: server, _base_server,
                                _threaded (ThreadedServer + EventServer), _prefork,
                                wsgi, _cron, transaction (the retrying() primitive)
                """,
            )
            report = smc.check(md, core)
            self.assertEqual(report.fictional, [], report.fictional)
            self.assertTrue(report.ok)


class LiveRepositoryTest(unittest.TestCase):
    """The gate against the real map — and proof it would notice a change."""

    def test_the_committed_map_is_clean(self):
        report = smc.check()
        self.assertEqual(report.fictional, [], "fictional paths in ARCHITECTURE.md")
        self.assertEqual(report.undocumented, [], "undocumented items")

    def test_the_map_enumerates_the_packages_we_expect(self):
        """Guards the parse itself: if the parser silently stopped
        understanding the map, ``enumerated`` would quietly shrink and every
        completeness check would pass vacuously."""
        report = smc.check()
        self.assertLessEqual(
            {"orm", "db", "http", "tools"}, set(report.enumerated) | {""}
        )
        # db/ is flat: all 18 modules must be named.
        self.assertGreaterEqual(len(report.enumerated.get("db", ())), 18)

    def test_removing_a_module_from_the_map_is_detected(self):
        """Mutation: drop one real module name and the gate must fail."""
        text = smc.ARCHITECTURE_MD.read_text(encoding="utf-8")
        self.assertIn("schema_cache", text)
        mutated = text.replace("savepoint, schema_cache,", "savepoint,", 1)
        self.assertNotEqual(mutated, text)
        with TemporaryDirectory() as tmp:
            md = Path(tmp) / "ARCHITECTURE.md"
            md.write_text(mutated, encoding="utf-8")
            report = smc.check(md, smc.CORE_ROOT)
            self.assertIn(("db", "schema_cache.py"), report.undocumented)

    def test_a_grouping_written_without_brackets_is_detected(self):
        """Mutation: revert the notation fix and the fiction reappears."""
        text = smc.ARCHITECTURE_MD.read_text(encoding="utf-8")
        mutated = text.replace("[connectivity]", "connectivity  ", 1)
        self.assertNotEqual(mutated, text)
        with TemporaryDirectory() as tmp:
            md = Path(tmp) / "ARCHITECTURE.md"
            md.write_text(mutated, encoding="utf-8")
            report = smc.check(md, smc.CORE_ROOT)
            self.assertFalse(report.ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
