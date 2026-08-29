from __future__ import annotations

import re
import unittest

import _doc_measures
import doc_restated_counts

from ._shared import (
    DOC,
    DOC_FLAT,
    ROOT,
)


class TestRiskRegisterFigures(unittest.TestCase):
    @staticmethod
    def _env_unsanctioned_private_members() -> dict[str, int]:
        import env_surface_check

        sanctioned = set(env_surface_check.SANCTIONED_PRIVATE)
        by_layer: dict[str, set[str]] = {}
        for reach in env_surface_check.check().reaches:
            if reach.is_private and reach.attr not in sanctioned:
                by_layer.setdefault(reach.layer, set()).add(reach.attr)
        return {layer: len(attrs) for layer, attrs in by_layer.items()}

    @staticmethod
    def _registry_sites() -> dict[str, int]:
        import pool_surface_check

        sites: dict[str, int] = {}
        for reach in pool_surface_check.check().reaches:
            sites[reach.layer] = sites.get(reach.layer, 0) + 1
        return sites

    def test_the_runtime_channel_figures_are_measured(self) -> None:

        privates = self._env_unsanctioned_private_members()
        sites = self._registry_sites()
        self.assertIn(
            f"{privates['Layer 1']} unsanctioned `Environment` privates against "
            f"Layer 2's {privates['Layer 2']}, and {sites['Layer 1']} Registry "
            f"sites against {sites['Layer 2']}",
            DOC_FLAT,
            f"the risk register's runtime-channel figures disagree with a live "
            f"run (env privates {privates}, registry sites {sites})",
        )

    def test_the_register_still_states_which_side_is_heavier(self) -> None:

        privates = self._env_unsanctioned_private_members()
        sites = self._registry_sites()
        self.assertGreater(privates["Layer 1"], privates["Layer 2"])
        self.assertGreater(sites["Layer 1"], sites["Layer 2"])
        self.assertIn("Layer 1 is the heavier consumer on both channels", DOC_FLAT)

    def test_no_page_states_a_checker_total_the_workflow_does_not_run(self) -> None:
        expected = len(_doc_measures.workflow_gates())
        phrasings = (
            (
                rf"\b(?:all|the)\s+({_doc_measures.ANY_NUMBER})\s+"
                rf"(?:blocking\s+)?boundary\s+checkers\b"
            ),
            rf"\bruns\s+\*\*({_doc_measures.ANY_NUMBER})\*\*\s+blocking\s+checkers\b",
            rf"\b({_doc_measures.ANY_NUMBER})\s+blocking\s+checkers\b",
            rf"\bCheckers\s+outside\s+the\s+({_doc_measures.ANY_NUMBER})\b",
            rf"\bsatisfy\s+all\s+({_doc_measures.ANY_NUMBER})\b",
            rf"\ball\s+({_doc_measures.ANY_NUMBER})\s+are\s+structural\b",
            rf"[-\u2014]\s*({_doc_measures.ANY_NUMBER})\s+gates\s+cannot\s+see\b",
        )
        wrong = [
            f"{page}: {match.group(0)!r} states "
            f"{_doc_measures.number_value(match.group(1))}"
            for phrasing in phrasings
            for page, match in _doc_measures.stated(phrasing)
            if _doc_measures.number_value(match.group(1)) != expected
        ]
        blocking = expected + len(_doc_measures.self_test_only_gates())
        wrong += [
            f"{page}: {match.group(0)!r} states "
            f"{_doc_measures.number_value(match.group(1))}, {blocking} block in all"
            for page, match in _doc_measures.stated(
                rf"\b({_doc_measures.ANY_NUMBER})\s+in\s+all\b"
            )
            if _doc_measures.number_value(match.group(1)) != blocking
        ]
        self.assertEqual(
            [],
            wrong,
            f"the workflow runs {expected} checkers, {blocking} block in all, "
            f"and a page says otherwise:\n  " + "\n  ".join(wrong),
        )
        self.assertTrue(
            any(_doc_measures.stated(phrasing) for phrasing in phrasings),
            "no page states the total any more; the phrasings have rotted",
        )

    def test_the_inventory_names_every_gate_outside_the_workflow(self) -> None:
        outside = _doc_measures.self_test_only_gates()
        section = DOC_FLAT.split("Checkers outside the", 1)[1].split(" is a ", 1)[0]
        missing = [gate for gate in outside if f"`{gate}.py`" not in section]
        self.assertEqual(
            [],
            missing,
            f"blocking through the self-test step and unnamed by the page: {missing}",
        )
        self.assertIn(
            f"{_doc_measures.number_word(len(outside)).capitalize()} more block",
            DOC_FLAT,
            f"{len(outside)} gates block outside the workflow's own steps",
        )

    def test_the_index_agrees_with_the_entry_bodies(self) -> None:
        risks = (ROOT / "doc" / "architecture" / "risks.md").read_text(encoding="utf-8")
        cells = dict(
            re.findall(r"^\| (R\d+) \|.*\| ([^|]*) \|\s*$", risks, re.MULTILINE)
        )
        headings = dict(re.findall(r"^## (R\d+) — (.*)$", risks, re.MULTILINE))
        self.assertEqual(
            sorted(cells),
            sorted(headings),
            "the index and the entry bodies list different risks",
        )
        wrong = []
        for rid, heading in sorted(headings.items()):
            closed = re.search(r"CLOSED (\d{4}-\d{2}-\d{2})", heading)
            cell = cells[rid].replace("*", "").strip()
            if closed and closed.group(1) not in cell:
                wrong.append(
                    f"{rid}: body says CLOSED {closed.group(1)}, index cell is {cell!r}"
                )
            elif not closed and cell not in ("—", ""):
                wrong.append(f"{rid}: index says closed {cell!r}, the body does not")
        self.assertEqual([], wrong, "\n  " + "\n  ".join(wrong))

    def test_the_public_surface_pin_size_is_measured(self) -> None:
        (measured,) = doc_restated_counts.public_surface_specifiers()
        self.assertIn(
            f"{measured} specifiers",
            DOC_FLAT,
            f"no page states the pin size ({measured} specifiers on disk); "
            f"`doc_restated_counts.py --update` writes it into risks.md",
        )
        wrong = [
            f"{page}: {match.group(0)!r}"
            for page, match in _doc_measures.stated(
                rf"\*\*({_doc_measures.ANY_NUMBER}) specifiers\*\*"
            )
            if _doc_measures.number_value(match.group(1)) != measured
        ]
        self.assertEqual(
            [],
            wrong,
            f"the pin holds {measured} specifiers and a page states another "
            f"figure in the same words — a history row states a past size as a "
            f"bare number in its own column, not as `**N specifiers**`:\n  "
            + "\n  ".join(wrong),
        )


class TestQualityFigureArithmetic(unittest.TestCase):
    def test_the_cold_over_warm_ratios_match_their_operands(self) -> None:
        pairs = re.findall(
            r"\*\*(\d+)× more\*\* than loading one \(([\d.]+) s against ([\d.]+) s\)",
            DOC_FLAT,
        )
        self.assertTrue(pairs, "the cold/warm ratio sentence changed shape")
        for stated, cold, warm in pairs:
            self.assertAlmostEqual(
                int(stated),
                float(cold) / float(warm),
                delta=1.0,
                msg=f"{cold}s / {warm}s is not {stated}×",
            )

    def test_the_remeasurement_table_ratio_row_is_consistent(self) -> None:
        self.assertIn(
            "**Re-measured",
            DOC,
            "Scenario 2's re-measurement is gone; a figure taken once and never "
            "repeated is what this page warns about",
        )
        section = DOC.split("**Re-measured", 1)[1].split("\n## ", 1)[0]
        rows = {
            m.group(1).strip(): (m.group(2).strip(), m.group(3).strip())
            for m in re.finditer(
                r"^\| ([^|]+?) \| ([^|]+?) \| ([^|]+?) \|$", section, re.MULTILINE
            )
        }
        ratio = next((v for k, v in rows.items() if "cold ÷ warm" in k), None)
        self.assertIsNotNone(ratio, "the re-measurement table lost its ratio row")
        build = next(v for k, v in rows.items() if "Install + build, registry" in k)
        warm = next(v for k, v in rows.items() if "Warm registry load" in k)

        def seconds(cell: str) -> float:
            return float(re.findall(r"[\d.]+", cell)[0])

        for column, (b, w, r) in enumerate(zip(build, warm, ratio, strict=True)):
            self.assertAlmostEqual(
                float(re.findall(r"\d+", r)[0]),
                seconds(b) / seconds(w),
                delta=1.5,
                msg=f"column {column}: {b} / {w} is not {r}",
            )

    LABELS = ("Stimulus", "Environment", "Response", "Measure")

    def _scenarios(self) -> dict[str, str]:
        headings = re.findall(r"^## (Scenario \d[^\n]*)", DOC, re.MULTILINE)
        self.assertGreaterEqual(
            len(headings), 4, "qualities.md lost its scenarios, or they were renamed"
        )
        return {
            heading: DOC.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
            for heading in headings
        }

    def test_every_scenario_carries_a_date(self) -> None:
        self.assertIn(
            "A number added to this page must arrive with its command and its date",
            DOC_FLAT,
        )
        undated = sorted(
            heading
            for heading, body in self._scenarios().items()
            if not re.search(r"20\d\d-\d\d-\d\d", body)
        )
        self.assertEqual(
            [],
            undated,
            f"a figure that is not dated will be read as current forever: {undated}",
        )

    def test_every_scenario_carries_its_command(self) -> None:
        uncommanded = sorted(
            heading
            for heading, body in self._scenarios().items()
            if not re.search(r"^Reproduce", body, re.MULTILINE)
        )
        self.assertEqual(
            [],
            uncommanded,
            f"the page's closing rule is that a number arrives with its "
            f"command; these state none: {uncommanded}",
        )

    def test_every_scenario_states_all_four_terms(self) -> None:
        missing = {
            heading: [label for label in self.LABELS if f"**{label}**" not in body]
            for heading, body in self._scenarios().items()
        }
        missing = {heading: gone for heading, gone in missing.items() if gone}
        self.assertEqual(
            {}, missing, f"a scenario is not in the stated shape: {missing}"
        )
