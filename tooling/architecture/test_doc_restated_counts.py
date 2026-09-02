from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

import doc_restated_counts as drc


def figure(name, path, pattern, values, render, tolerance=0.0):
    return drc.Figure(
        name, path, re.compile(pattern), lambda: values, render, tolerance
    )


class ReportedValues(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "guidelines.rst"

    def _one(self, prose, pattern, values, render, tolerance=0.0):
        self.path.write_text(prose, encoding="utf-8")
        return drc.check(
            [figure("probe", self.path, pattern, values, render, tolerance)]
        )

    def test_a_grouped_figure_is_reported_grouped(self):
        problems = self._one(
            "the census counts 24,354 definitions",
            r"counts\s+([\d,]+)\s+definitions",
            (24397,),
            drc._grouped,
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("states 24,354, measured 24,397", problems[0])
        self.assertNotIn("measured 24397", problems[0])

    def test_a_tenths_figure_is_reported_as_a_decimal(self):
        problems = self._one(
            "of the definitions it is 22.1 %",
            r"definitions\s+it\s+is\s+([\d.]+)\s*%",
            (220,),
            drc._tenths,
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("states 22.1, measured 22.0", problems[0])
        self.assertNotIn("measured 220", problems[0])

    def test_a_padded_figure_is_reported_padded(self):
        problems = self._one(
            "item 0012 records it",
            r"item (\d+)\s+records",
            (7,),
            drc._padded,
        )
        self.assertIn("states 0012, measured 0007", problems[0])

    def test_a_fresh_figure_is_not_reported(self):
        self.assertEqual(
            self._one(
                "the census counts 24,397 definitions",
                r"counts\s+([\d,]+)\s+definitions",
                (24397,),
                drc._grouped,
            ),
            [],
        )

    def test_a_figure_inside_its_tolerance_is_not_reported(self):
        self.assertEqual(
            self._one(
                "about 1,000 sites",
                r"about\s+([\d,]+)\s+sites",
                (1020,),
                drc._rounded,
                tolerance=0.05,
            ),
            [],
        )

    def test_a_figure_outside_its_tolerance_is_reported_rendered(self):
        problems = self._one(
            "about 1,000 sites",
            r"about\s+([\d,]+)\s+sites",
            (2000,),
            drc._rounded,
            tolerance=0.05,
        )
        self.assertIn("states 1,000, measured 2000", problems[0])


class Updating(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "guidelines.rst"

    def test_update_writes_the_rendered_form_back(self):
        self.path.write_text("the census counts 24,354 definitions", "utf-8")
        one = figure(
            "probe",
            self.path,
            r"counts\s+([\d,]+)\s+definitions",
            (24397,),
            drc._grouped,
        )
        self.assertEqual(drc.update([one]), ["probe: 24,397"])
        self.assertEqual(
            self.path.read_text("utf-8"), "the census counts 24,397 definitions"
        )
        self.assertEqual(drc.check([one]), [])

    def test_a_missing_sentence_names_the_figure_and_the_pattern(self):
        self.path.write_text("nothing to match here", "utf-8")
        one = figure(
            "probe", self.path, r"counts\s+([\d,]+)\s+definitions", (1,), drc._grouped
        )
        with self.assertRaises(LookupError) as caught:
            drc.check([one])
        self.assertIn("probe", str(caught.exception))
        self.assertIn("drop the figure from FIGURES", str(caught.exception))


class EveryFigureRoundTrips(unittest.TestCase):
    def test_update_then_check_is_clean_for_every_renderer(self):
        for render, measured, prose, pattern in (
            (drc._plain, (7,), "counts 3 things", r"counts\s+(\d+)\s+things"),
            (
                drc._grouped,
                (1234567,),
                "counts 3 things",
                r"counts\s+([\d,]+)\s+things",
            ),
            (drc._padded, (7,), "item 0001 says", r"item (\d+)\s+says"),
            (drc._rounded, (1234,), "about 3 sites", r"about\s+([\d,]+)\s+sites"),
            (drc._tenths, (221,), "it is 1.0 %", r"it\s+is\s+([\d.]+)\s*%"),
        ):
            with self.subTest(render=render.__name__):
                tmp = TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                path = Path(tmp.name) / "doc.rst"
                path.write_text(prose, encoding="utf-8")
                one = figure("probe", path, pattern, measured, render)
                drc.update([one])
                self.assertEqual(
                    drc.check([one]),
                    [],
                    f"{render.__name__} writes a form its own pattern rejects",
                )


def table(name, path, rows):
    return drc.Table(
        name,
        path,
        tuple(
            drc.Row(n, section, label, lambda v=v: v) for n, section, label, v in rows
        ),
    )


class CensusTable(unittest.TestCase):
    ROWS = (("a", "§1", "Things", 3), ("b", "§2", "Other ``things``", 1200))

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "guidelines.rst"
        self.path.write_text(
            "before\n\n.. probe-table-start\n.. probe-table-end\n\nafter\n", "utf-8"
        )
        self.table = table("probe", self.path, self.ROWS)

    def test_a_page_without_the_markers_names_the_table(self):
        self.path.write_text("no markers here", "utf-8")
        with self.assertRaises(LookupError) as caught:
            drc.check([self.table])
        self.assertIn("probe", str(caught.exception))
        self.assertIn(".. probe-table-start", str(caught.exception))

    def test_a_block_with_no_rows_reports_every_row_as_missing(self):
        problems = drc.check([self.table])
        self.assertEqual(len(problems), 2)
        self.assertIn(
            "probe.a in guidelines.rst: no row labelled 'Things'", problems[0]
        )

    def test_update_writes_the_table_and_check_is_clean(self):
        changed = drc.update([self.table])
        self.assertEqual(changed, ["probe.a: 3", "probe.b: 1,200"])
        text = self.path.read_text("utf-8")
        self.assertTrue(text.startswith("before\n\n.. probe-table-start\n"))
        self.assertTrue(text.endswith(".. probe-table-end\n\nafter\n"))
        self.assertIn("Other ``things``", text)
        self.assertRegex(text, r"§2\s+Other ``things``\s+1,200\n")
        self.assertEqual(drc.check([self.table]), [])
        self.assertEqual(drc.update([self.table]), [])

    def test_a_drifted_row_is_reported_by_row_name(self):
        drc.update([self.table])
        moved = table(
            "probe", self.path, (self.ROWS[0], ("b", "§2", "Other ``things``", 1300))
        )
        problems = drc.check([moved])
        self.assertEqual(len(problems), 1)
        self.assertIn(
            "probe.b in guidelines.rst: states 1,200, measured 1,300", problems[0]
        )

    def test_a_hand_edited_block_is_reported_even_when_every_row_agrees(self):
        drc.update([self.table])
        text = self.path.read_text("utf-8").replace("Count\n", "Count\n\n", 1)
        self.path.write_text(text, "utf-8")
        problems = drc.check([self.table])
        self.assertEqual(len(problems), 1)
        self.assertIn("not in its generated form", problems[0])
        drc.update([self.table])
        self.assertEqual(drc.check([self.table]), [])

    def test_update_of_one_row_leaves_the_others_as_stated(self):
        drc.update([self.table])
        moved = table(
            "probe",
            self.path,
            (("a", "§1", "Things", 4), ("b", "§2", "Other ``things``", 1300)),
        )
        self.assertEqual(drc.update([moved], rows={"a"}), ["probe.a: 4"])
        text = self.path.read_text("utf-8")
        self.assertRegex(text, r"Things\s+4\n")
        self.assertRegex(text, r"Other ``things``\s+1,200\n")
        self.assertEqual(drc.update([moved]), ["probe.b: 1,300"])
        self.assertEqual(drc.check([moved]), [])


class Selecting(unittest.TestCase):
    def setUp(self):
        path = Path("/nowhere/guidelines.rst")
        self.first = figure("first", path, r"(\d+)", (1,), drc._plain)
        self.second = figure("second", path, r"(\d+)", (2,), drc._plain)
        self.table = table(
            "census", path, (("row_a", "§1", "A", 1), ("row_b", "§1", "B", 2))
        )
        self.items = (self.first, self.second, self.table)

    def test_a_figure_name_selects_only_that_figure(self):
        self.assertEqual(drc.select(["second"], self.items), ([self.second], None))

    def test_a_row_name_selects_its_table_and_restricts_the_rows(self):
        chosen, rows = drc.select(["row_b", "first"], self.items)
        self.assertEqual(chosen, [self.table, self.first])
        self.assertEqual(rows, frozenset({"row_b"}))

    def test_a_table_name_selects_every_row(self):
        self.assertEqual(
            drc.select(["row_a", "census"], self.items), ([self.table], None)
        )

    def test_an_unknown_name_lists_the_known_ones(self):
        with self.assertRaises(LookupError) as caught:
            drc.select(["nope"], self.items)
        message = str(caught.exception)
        for name in ("'nope'", "first", "second", "census", "row_a"):
            self.assertIn(name, message)

    def test_every_real_name_is_unique_across_figures_tables_and_rows(self):
        names = [item.name for item in drc.ITEMS]
        names += [row.name for item in drc.TABLES for row in item.rows]
        self.assertEqual(sorted(names), sorted(set(names)))

    def test_every_real_row_is_addressed_by_a_unique_section_and_label(self):
        for item in drc.TABLES:
            keys = [(row.section, row.label) for row in item.rows]
            self.assertEqual(
                sorted(keys),
                sorted(set(keys)),
                f"{item.name}: two rows share a section and a label, so a stated "
                f"value cannot be read back to its row",
            )


class Main(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rst = Path(self.tmp.name) / "guidelines.rst"
        self.rst.write_text("apples 1 and pears 1", "utf-8")
        self.md = Path(self.tmp.name) / "risks.md"
        self.md.write_text("plums 1", "utf-8")
        self.items = (
            figure("apples", self.rst, r"apples (\d+)", (2,), drc._plain),
            figure("pears", self.rst, r"pears (\d+)", (3,), drc._plain),
            figure("plums", self.md, r"plums (\d+)", (4,), drc._plain),
        )

    def _main(self, *argv):
        import contextlib
        import io

        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = drc.main(list(argv), self.items)
        return code, out.getvalue()

    def test_check_groups_the_drift_by_page_and_exits_1(self):
        code, out = self._main("--check")
        self.assertEqual(code, 1)
        self.assertEqual(
            out.splitlines(),
            [
                "guidelines.rst",
                "  apples: states 1, measured 2",
                "  pears: states 1, measured 3",
                "risks.md",
                "  plums: states 1, measured 4",
            ],
        )
        self.assertEqual(
            drc.check_by_page(self.items),
            {
                "guidelines.rst": [
                    "apples: states 1, measured 2",
                    "pears: states 1, measured 3",
                ],
                "risks.md": ["plums: states 1, measured 4"],
            },
        )

    def test_a_bare_run_reports_and_exits_0(self):
        code, out = self._main()
        self.assertEqual(code, 0)
        self.assertIn("apples: states 1, measured 2", out)

    def test_update_of_named_figures_refreshes_only_those(self):
        code, out = self._main("--update", "apples", "plums")
        self.assertEqual((code, out.strip()), (0, "apples: 2\nplums: 4"))
        self.assertEqual(self.rst.read_text("utf-8"), "apples 2 and pears 1")
        self.assertEqual(self.md.read_text("utf-8"), "plums 4")
        self.assertEqual(
            drc.check(self.items), ["pears in guidelines.rst: states 1, measured 3"]
        )

    def test_a_bare_update_refreshes_everything(self):
        code, _out = self._main("--update")
        self.assertEqual(code, 0)
        self.assertEqual(drc.check(self.items), [])
        self.assertEqual(self._main("--check"), (0, ""))

    def test_an_unknown_name_exits_2_and_writes_nothing(self):
        code, out = self._main("--update", "apples", "quinces")
        self.assertEqual(code, 2)
        self.assertIn("'quinces' names no figure", out)
        self.assertEqual(self.rst.read_text("utf-8"), "apples 1 and pears 1")


class RealTree(unittest.TestCase):
    ARCHITECTURE = drc.ROOT / "doc" / "architecture"

    def test_the_partition_covers_every_figure(self):
        here = drc.figures_for(drc.ROOT / "doc", drc.ITEMS)
        elsewhere = [f for f in drc.ITEMS if f not in here]
        self.assertEqual(
            len(here) + len(elsewhere),
            len(drc.ITEMS),
            "the two halves must partition ITEMS, or a figure is checked twice "
            "or not at all",
        )
        self.assertTrue(drc.figures_for(self.ARCHITECTURE), "no architecture figure")
        self.assertEqual(
            drc.figures_for(self.ARCHITECTURE, drc.TABLES),
            (),
            "a census table on an architecture page is checked by two suites",
        )

    def test_the_census_table_lives_in_the_guidelines(self):
        self.assertEqual([t.path for t in drc.TABLES], [drc.GUIDELINES])
        self.assertIn(drc.CENSUS.start, drc.GUIDELINES.read_text(encoding="utf-8"))

    def test_every_figure_outside_the_architecture_pages_is_fresh(self):
        architecture = set(drc.figures_for(self.ARCHITECTURE, drc.ITEMS))
        items = tuple(f for f in drc.ITEMS if f not in architecture)
        self.assertTrue(items, "every figure now measures doc/architecture")
        problems = drc.check(items)
        self.assertFalse(
            problems,
            "prose figures have drifted from what the tree measures; run "
            "`python tooling/architecture/doc_restated_counts.py --update` "
            "(or `--update <name>` for the one your commit moved):\n  "
            + "\n  ".join(problems),
        )


if __name__ == "__main__":
    unittest.main()
