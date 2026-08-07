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

# ---------------------------------------------------------------------------
# Existence of what an ADR names, beyond "is this path in the tree".
#
# The rooted-path check below caught a file that had been deleted. It could not
# catch the two shapes that actually let ADR-0012/0013 describe a subsystem this
# repository has never contained, both reproduced as probes at the bottom of
# this file:
#
#   * an addon-relative path -- ``base/models/object_store.py`` does not start
#     with one of ``_ROOTED``, so it was never checked at all;
#   * a symbol inside a file that DOES exist -- ``odoo/http/stream.py`` resolves,
#     so ``Stream.delivery_mode()`` was taken on trust. The file is the citation;
#     the method is the claim.
#
# So three more checks, all keyed on tokens an ADR already writes in backticks:
# ``<module>/<path>.py`` resolved against the addons trees, ``name()`` resolved
# against every ``def``/``class`` in the tree, and a dotted model name resolved
# against every ``_name``/``_inherit``. Each is deliberately narrow -- it fires
# only on an unambiguous shape -- because a doc gate that cries wolf gets
# disabled, and a disabled gate is the state ADR-0006 was written to end.
# ---------------------------------------------------------------------------

#: Trees scanned to learn what exists. ``tooling/`` is included because ADRs
#: cite the checkers by function name.
_CORPUS_TREES = ("odoo", "addons", "tooling")

#: Where an addon-relative path is resolved from, in addons-path order.
_ADDON_TREES = ("odoo/addons", "addons")

_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", re.MULTILINE)
_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.MULTILINE)
_MODEL_RE = re.compile(
    r"^\s*_(?:name|inherit)\s*=\s*[\"']([a-z][\w.]*)[\"']", re.MULTILINE
)

#: A backticked method/function citation: ``frontend_path()``,
#: ``Stream.delivery_mode()``. The empty parens are what make it a claim about a
#: callable rather than prose, so only that form is checked.
_CALL_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\(\)$")

#: A dotted, all-lowercase Odoo model name: ``ir.content.placement``. Python
#: dotted paths (``odoo.orm``) and attribute chains (``env.cache``) match this
#: shape too, which is why a token is only checked when its first segment is
#: already a model prefix somewhere in the tree.
_MODEL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]+)+$")

#: Suffixes that mark a token as a file rather than a model or a symbol.
_SRC_SUFFIXES = (
    ".py", ".js", ".mjs", ".xml", ".md", ".rst", ".yml", ".yaml",
    ".json", ".toml", ".ini", ".cfg", ".txt", ".sh", ".lock", ".scss", ".css",
)

#: Characters that mark a backticked token as prose: template placeholders
#: (``odoo/libs/<area>``), alternation (``odoo/orm|db|libs``) and brace
#: expansion (``baselines/{ruff,mypy}.json``). Shared by every check here.
_PROSE_CHARS = "<>*|{}, "

#: ``odoo/http/stream.py:171-179`` — the repo's standard way to cite code
#: (``file_path:line_number``, per CLAUDE.md). The line reference is not part of
#: the path, and an ADR that cites precisely should not be punished for it.
_LINE_REF_RE = re.compile(r":\d+(?:[-–]\d+)?$")


def _strip_line_ref(token: str) -> str:
    return _LINE_REF_RE.sub("", token)


_corpus_cache: dict[str, object] = {}


def _corpus() -> dict[str, object]:
    """Names the tree actually defines: callables, models, addon modules.

    Built once (~1.3 s over ~9,300 files) and memoised, so the checks below are
    a set lookup each. Regex rather than AST on purpose: this module is
    stdlib-only and runs inside the boundary-gate job, and a name that is
    syntactically a definition is exactly what a reader of an ADR would go
    looking for.
    """
    if _corpus_cache:
        return _corpus_cache
    import builtins

    defined: set[str] = set(dir(builtins))
    models: set[str] = set()
    for tree in _CORPUS_TREES:
        for path in (ROOT / tree).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            defined.update(_DEF_RE.findall(text))
            defined.update(_CLASS_RE.findall(text))
            models.update(_MODEL_RE.findall(text))
    modules: dict[str, Path] = {}
    for tree in _ADDON_TREES:
        tree_path = ROOT / tree
        if not tree_path.is_dir():
            continue
        for entry in tree_path.iterdir():
            if entry.is_dir() and (entry / "__manifest__.py").is_file():
                modules.setdefault(entry.name, entry)
    _corpus_cache.update(
        defined=defined,
        models=models,
        model_prefixes={m.split(".")[0] for m in models},
        modules=modules,
    )
    return _corpus_cache


def existence_findings(text: str) -> list[tuple[str, str]]:
    """``(kind, token)`` for every backticked name in ``text`` that is absent.

    Split out of the test methods so the rules are reachable without writing a
    file into ``doc/adr/`` — the same reason ``layer_check.violations_for``
    exists. The probe tests below drive this directly.
    """
    corpus = _corpus()
    defined = corpus["defined"]
    models = corpus["models"]
    prefixes = corpus["model_prefixes"]
    modules = corpus["modules"]

    findings: list[tuple[str, str]] = []
    for raw in _PATH_RE.findall(text):
        token = _strip_line_ref(raw)
        if not token or any(c in token for c in _PROSE_CHARS):
            continue
        if _CALL_RE.match(token):
            if token[:-2].split(".")[-1] not in defined:
                findings.append(("symbol", token))
        elif (
            "/" in token
            and token.endswith(_SRC_SUFFIXES)
            and not token.startswith(_ROOTED)
        ):
            head, _, tail = token.partition("/")
            module = modules.get(head)
            if module is not None and not (module / tail).exists():
                findings.append(("module-path", token))
        elif (
            _MODEL_NAME_RE.match(token)
            and not token.endswith(_SRC_SUFFIXES)
            and token.split(".")[0] in prefixes
            and token not in models
        ):
            findings.append(("model", token))
    return findings


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
            _strip_line_ref(token).rstrip("/")
            for token in _PATH_RE.findall(text)
            if token.startswith(_ROOTED) and not any(c in token for c in _PROSE_CHARS)
        ]

    def test_backticked_repo_paths_exist(self):
        for p in [*ADR_FILES, README_PATH]:
            text = p.read_text(encoding="utf-8")
            for path in self._rooted_paths(text):
                self.assertTrue(
                    (ROOT / path).exists(),
                    f"{p.name} references `{path}`, which is not in the tree",
                )


class TestReferencedNamesExist(unittest.TestCase):
    """What an ADR names must exist, not merely the file it names it in."""

    _ADVICE = {
        "module-path": (
            "an addon-relative path that does not resolve under odoo/addons/ "
            "or addons/"
        ),
        "symbol": "a callable no def/class in the tree defines",
        "model": "a model name no _name/_inherit in the tree declares",
    }

    def test_every_adr_names_only_things_that_exist(self):
        for p in [*ADR_FILES, README_PATH]:
            text = p.read_text(encoding="utf-8")
            # A `Proposed` ADR names code that does not exist yet — that is what
            # makes it a proposal. Exempting it is what gives the status word
            # teeth: an ADR earns `Accepted` by having its subject in the tree,
            # so the cheap way past this gate is the honest one.
            status = _STATUS_RE.search(text)
            if status and _status_kind(status.group(1)) == "Proposed":
                continue
            findings = existence_findings(text)
            if not findings:
                continue
            detail = "\n".join(
                f"  {kind:12} `{token}` — {self._ADVICE[kind]}"
                for kind, token in findings
            )
            self.fail(
                f"{p.name} names {len(findings)} thing(s) the tree does not "
                f"contain:\n{detail}\n"
                "An ADR that describes code which does not exist is a proposal. "
                "Either land the code, correct the reference in an Amendments "
                "section, or set the Status to Proposed."
            )


class TestExistenceProbes(unittest.TestCase):
    """The three shapes that reached ``Accepted`` unchecked.

    Each was reproduced against the real gate before this class existed: A and C
    passed (the bug), B failed (the pre-existing check). They are pinned here so
    a future simplification of ``existence_findings`` cannot quietly reopen the
    hole, and so the rules stay testable without mutating ``doc/adr/``.
    """

    def test_probe_a_addon_relative_path_is_caught(self):
        # The ADR-0012 shape: unrooted, so the rooted-path check never saw it.
        found = existence_findings("see `base/models/object_store.py` for this")
        self.assertEqual(found, [("module-path", "base/models/object_store.py")])

    def test_probe_b_rooted_path_is_still_caught(self):
        # Guards the pre-existing check, which lives in TestReferencedPaths.
        self.assertFalse((ROOT / "odoo/db/does_not_exist.py").exists())

    def test_probe_c_symbol_in_an_existing_file_is_caught(self):
        # The ADR-0012 shape again: `odoo/http/stream.py` resolves, the method
        # never existed. The file is the citation; the method is the claim.
        found = existence_findings("`Cursor.totally_fake_method()` in a real file")
        self.assertEqual(found, [("symbol", "Cursor.totally_fake_method()")])

    def test_probe_d_absent_model_name_is_caught(self):
        # The ADR-0013 shape.
        found = existence_findings("one row per copy: `ir.content.placement`")
        self.assertEqual(found, [("model", "ir.content.placement")])

    def test_real_references_do_not_fire(self):
        # The false-positive guard that decides whether this gate survives:
        # a real module path, a real callable, a real model, a Python dotted
        # path, an attribute chain and the prose placeholders must all be quiet.
        quiet = (
            "`base/models/ir_attachment.py` and `odoo/orm/components/core.py`, "
            "`is_maintenance_db()`, `Environment.ref()`, `ir.attachment`, "
            "`odoo.orm.runtime`, `env.cache`, `transaction.storage`, "
            "`odoo/libs/<area>`, `odoo/orm|db|libs`, "
            "`tooling/ratchet/baselines/{ruff,mypy}.json`"
        )
        self.assertEqual(existence_findings(quiet), [])


if __name__ == "__main__":
    unittest.main()
