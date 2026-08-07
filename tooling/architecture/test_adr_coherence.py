#!/usr/bin/env python3
"""Fact-check ``doc/adr/`` against itself and the tree.

The prose gates work — ``subsystem_map_check`` keeps ``ARCHITECTURE.md``'s map
honest, ``package_index_check`` keeps the package READMEs honest, and
``test_architecture_doc`` fact-checks the overview page. The Architecture
Decision Records sat outside all of them, and rotted the same way: ADR-0004's
"shim story" once named files that no longer existed, caught only by a manual
audit. An ADR is immutable once accepted, which makes a *reference* inside it
age badly — the decision text is frozen while the tree it points at moves.

This closes that gap with the same discipline the other doc gates use: it never
re-derives a decision, it only asserts that what an ADR *states about the repo*
still agrees with the repo. Specifically —

* **Index ↔ files, both ways** — every ``NNNN-*.md`` is a row in
  ``doc/adr/README.md``'s table, and every row links to a file that exists whose
  number matches (the ``package_index_check`` rule, for the ADR index).
* **Row ↔ heading agreement** — a row's title and status match the ADR's own
  ``# ADR-NNNN:`` heading and ``**Status:**`` line (status by *kind* —
  ``Accepted`` / ``Proposed`` / ``Superseded`` — since ADR-0010 qualifies its
  ``Accepted`` with parenthetical detail the one-word index cell omits).
* **Well-formedness** — each ADR carries a heading whose number matches its
  filename, a ``**Status:**`` and an ISO ``**Date:**`` line, and the template's
  load-bearing sections (Context, Decision, Consequences).
* **Cross-references resolve** — every ``ADR-NNNN`` named in a body, and any
  ``Superseded by ADR-NNNN`` target, points at an ADR that exists; the numbers
  are contiguous from 0001 with no gap or duplicate.
* **Referenced repo paths exist** — every backticked, *unambiguously
  repo-rooted* path (``odoo/…``, ``tooling/…``, ``addons/…``, ``doc/…``,
  ``crates/…``, ``.github/…``) resolves on disk. Bare filenames (``api.py``, or
  the historical ``sql_db.py`` that ADR-0003 decomposed away) are deliberately
  NOT checked: they are ambiguous or describe a pre-decomposition state, and
  demanding they exist would fail an ADR for correctly recording history.

Stdlib-only, so it runs in the boundary-gate job (pytest and nothing else).
Run directly or under pytest; the ``Architecture Boundaries`` workflow runs the
whole ``tooling/architecture/`` directory.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="test_adr_coherence")
ADR_DIR = ROOT / "doc" / "adr"
README_PATH = ADR_DIR / "README.md"
README = README_PATH.read_text(encoding="utf-8")

#: The ``NNNN-slug.md`` records, sorted by number.
ADR_FILES: list[Path] = sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))

#: Sections the template calls load-bearing (``Enforcement`` is "if any", so it
#: is not required — 0012/0013 legitimately omit it).
REQUIRED_SECTIONS = ("Context", "Decision", "Consequences")

#: Top-level directories that make a backticked token an unambiguous repo path.
_ROOTED = ("odoo/", "tooling/", "addons/", "doc/", "crates/", ".github/")

_ROW_RE = re.compile(
    r"^\|\s*\[(\d{4})\]\(([^)]+)\)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$", re.MULTILINE
)
_H1_RE = re.compile(r"^#\s*ADR-(\d{4}):\s*(.+?)\s*$", re.MULTILINE)
_STATUS_RE = re.compile(r"^-\s*\*\*Status:\*\*\s*(.+?)\s*$", re.MULTILINE)
_DATE_RE = re.compile(r"^-\s*\*\*Date:\*\*\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_PATH_RE = re.compile(r"`([^`]+)`")


def _status_kind(status: str) -> str:
    """The status word the index cell carries — the first token."""
    return status.split(maxsplit=1)[0] if status else ""


def _norm_title(title: str) -> str:
    """A title compared for *wording*, not typography.

    The index and an ADR heading may disagree on inline-code backticks — the
    index writes ``(`env.backend`)`` where ADR-0011's heading writes
    ``(env.backend)`` — and an ADR is immutable once accepted, so the gate must
    not force a cosmetic edit. Stripping backticks and collapsing whitespace
    still catches a title whose *words* drifted.
    """
    return " ".join(title.replace("`", "").split())


def _index_rows() -> dict[str, tuple[str, str, str]]:
    """``{number: (link_target, title, status)}`` from the README table."""
    return {
        m.group(1): (m.group(2), m.group(3), m.group(4))
        for m in _ROW_RE.finditer(README)
    }


def _adr_text(number: str) -> str:
    for p in ADR_FILES:
        if p.name[:4] == number:
            return p.read_text(encoding="utf-8")
    raise KeyError(number)


class TestIndexCoherence(unittest.TestCase):
    def test_every_adr_file_is_indexed(self):
        rows = _index_rows()
        for p in ADR_FILES:
            self.assertIn(p.name[:4], rows, f"{p.name} has no row in doc/adr/README.md")

    def test_every_index_row_points_to_an_existing_matching_file(self):
        for number, (link, _title, _status) in _index_rows().items():
            target = ADR_DIR / link
            self.assertTrue(
                target.is_file(),
                f"README row {number} links to {link}, which does not exist",
            )
            self.assertEqual(
                target.name[:4],
                number,
                f"README row {number} links to {link}, whose number differs",
            )

    def test_index_title_matches_the_adr_heading(self):
        for number, (_link, title, _status) in _index_rows().items():
            h1 = _H1_RE.search(_adr_text(number))
            self.assertIsNotNone(h1, f"ADR-{number} has no `# ADR-{number}:` heading")
            self.assertEqual(
                _norm_title(title),
                _norm_title(h1.group(2)),
                f"README title for {number} disagrees with the ADR heading",
            )

    def test_index_status_matches_the_adr_status_kind(self):
        for number, (_link, _title, status) in _index_rows().items():
            m = _STATUS_RE.search(_adr_text(number))
            self.assertIsNotNone(m, f"ADR-{number} has no **Status:** line")
            self.assertEqual(
                _status_kind(status),
                _status_kind(m.group(1)),
                f"README status kind for {number} disagrees with the ADR",
            )


class TestWellFormedness(unittest.TestCase):
    def test_heading_number_matches_filename(self):
        for p in ADR_FILES:
            h1 = _H1_RE.search(p.read_text(encoding="utf-8"))
            self.assertIsNotNone(h1, f"{p.name} has no `# ADR-NNNN:` heading")
            self.assertEqual(
                h1.group(1), p.name[:4], f"{p.name} heading number != filename"
            )

    def test_each_adr_has_status_and_iso_date(self):
        for p in ADR_FILES:
            text = p.read_text(encoding="utf-8")
            self.assertIsNotNone(
                _STATUS_RE.search(text), f"{p.name} is missing a **Status:** line"
            )
            self.assertIsNotNone(
                _DATE_RE.search(text),
                f"{p.name} is missing an ISO **Date:** (YYYY-MM-DD) line",
            )

    def test_each_adr_has_the_required_sections(self):
        for p in ADR_FILES:
            sections = set(_SECTION_RE.findall(p.read_text(encoding="utf-8")))
            missing = set(REQUIRED_SECTIONS) - sections
            self.assertFalse(
                missing, f"{p.name} is missing required section(s): {sorted(missing)}"
            )


class TestCrossReferences(unittest.TestCase):
    def _existing_numbers(self) -> set[str]:
        return {p.name[:4] for p in ADR_FILES}

    def test_numbers_are_contiguous_from_one(self):
        nums = sorted(int(p.name[:4]) for p in ADR_FILES)
        self.assertEqual(
            nums,
            list(range(1, len(nums) + 1)),
            f"ADR numbers are not contiguous 1..N: {nums}",
        )

    def test_body_cross_references_resolve(self):
        existing = self._existing_numbers()
        for p in ADR_FILES:
            for num in set(re.findall(r"ADR-(\d{4})", p.read_text(encoding="utf-8"))):
                self.assertIn(
                    num,
                    existing,
                    f"{p.name} references ADR-{num}, which does not exist",
                )

    def test_superseded_targets_exist(self):
        existing = self._existing_numbers()
        for p in ADR_FILES:
            m = _STATUS_RE.search(p.read_text(encoding="utf-8"))
            if not m:
                continue
            sup = re.search(r"Superseded by ADR-(\d{4})", m.group(1))
            if sup:
                self.assertIn(
                    sup.group(1),
                    existing,
                    f"{p.name} is superseded by ADR-{sup.group(1)}, which is absent",
                )


class TestReferencedPaths(unittest.TestCase):
    def _rooted_paths(self, text: str) -> list[str]:
        # A repo-rooted token, minus the shorthand notations ADRs write inside
        # backticks: template placeholders (``odoo/libs/<area>``), alternation
        # (``odoo/orm|db|libs``) and brace expansion
        # (``tooling/ratchet/baselines/{ruff,mypy}.json``). None can appear in a
        # real path, so a token carrying any of ``< > * | { } , space`` is prose,
        # not a file reference.
        return [
            token.rstrip("/")
            for token in _PATH_RE.findall(text)
            if token.startswith(_ROOTED) and not any(c in token for c in "<>*|{}, ")
        ]

    def test_backticked_repo_paths_exist(self):
        for p in [*ADR_FILES, README_PATH]:
            text = p.read_text(encoding="utf-8")
            for path in self._rooted_paths(text):
                self.assertTrue(
                    (ROOT / path).exists(),
                    f"{p.name} references `{path}`, which is not in the tree",
                )


if __name__ == "__main__":
    unittest.main()
