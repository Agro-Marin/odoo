from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import subsystem_map_check as smc


def write_map(root: Path, body: str) -> Path:
    md = root / "ARCHITECTURE.md"
    md.write_text(
        "# Title\n\nprose\n\n## Subsystem map\n\n```\n"
        + textwrap.dedent(body).strip("\n")
        + "\n```\n\ntrailing prose\n",
        encoding="utf-8",
    )
    return md


def make_tree(root: Path, spec: dict[str, list[str]]) -> Path:
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
    def test_a_bare_list_is_all_names(self):
        names, complete = smc.parse_names("pool, cursor, ddl")
        self.assertEqual([n for n, _ in names], ["pool", "cursor", "ddl"])
        self.assertTrue(complete)

    def test_a_description_stops_the_list_after_its_subject(self):

        names, complete = smc.parse_names(
            "service/        Process lifecycle + servers: server, _base_server,"
        )
        self.assertEqual(names, [("service", True)])
        self.assertFalse(complete)

    def test_one_space_between_name_and_prose_still_stops(self):
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
        modules, _packages = smc._actual_children("upgrade_code", smc.CORE_ROOT)
        self.assertTrue(modules, "upgrade_code has no modules — probe is vacuous")
        for stem in sorted(modules):
            with self.subTest(stem=stem):
                self.assertEqual(smc.parse_names(stem), ([(stem, False)], True))

    def test_widening_did_not_break_the_prose_boundary(self):
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
        self.assertEqual(first, 4)


class FictionalPathTest(unittest.TestCase):
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
    def test_the_committed_map_is_clean(self):
        report = smc.check()
        self.assertEqual(report.fictional, [], "fictional paths in ARCHITECTURE.md")
        self.assertEqual(report.undocumented, [], "undocumented items")

    def test_the_map_enumerates_the_packages_we_expect(self):
        report = smc.check()
        self.assertLessEqual(
            {"orm", "db", "http", "tools"}, set(report.enumerated) | {""}
        )
        self.assertGreaterEqual(len(report.enumerated.get("db", ())), 18)

    def test_removing_a_module_from_the_map_is_detected(self):
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
