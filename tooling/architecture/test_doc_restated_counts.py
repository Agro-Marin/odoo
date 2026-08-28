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
    """The doc states figures in a rendered form -- grouped, in tenths, padded.
    A message that prints the raw measurement beside the stated one reads as a
    parse failure rather than as drift, which is how `states 22.1, measured 220`
    was first mistaken for a broken regex.
    """

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
            "ADR-0012 records it",
            r"ADR-(\d+)\s+records",
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
    """A render whose output its own pattern cannot match again would make the
    figure permanently stale: --update writes a form --check rejects."""

    def test_update_then_check_is_clean_for_every_renderer(self):
        for render, measured, prose, pattern in (
            (drc._plain, (7,), "counts 3 things", r"counts\s+(\d+)\s+things"),
            (
                drc._grouped,
                (1234567,),
                "counts 3 things",
                r"counts\s+([\d,]+)\s+things",
            ),
            (drc._padded, (7,), "ADR-0001 says", r"ADR-(\d+)\s+says"),
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


if __name__ == "__main__":
    unittest.main()
