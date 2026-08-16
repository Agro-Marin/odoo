#!/usr/bin/env python3


from __future__ import annotations

import json
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

ADR_FILES: list[Path] = sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))

REQUIRED_SECTIONS = ("Context", "Decision", "Consequences")

ALTERNATIVES_REQUIRED_FROM = 14

SECTION_ORDER_REQUIRED_FROM = 19
ENFORCEMENT_ANSWER_REQUIRED_FROM = 19

IMPLEMENTATION_STATUS_FORBIDDEN_FROM = 36

TEMPLATE_SECTION_ORDER = (
    "Context",
    "Decision",
    "Alternatives considered",
    "Consequences",
    "Enforcement",
    "Amendments",
)

STATUS_KINDS = frozenset({"Draft", "Proposed", "Accepted", "Superseded", "Withdrawn"})

UNBUILT_STATUS_KINDS = frozenset({"Draft", "Proposed", "Withdrawn"})

_AMENDMENTS_HEADING = "## Amendments"

_LIVE_STATUS_RES = (
    re.compile(r"currently\s+\*{0,2}(?:clean|zero)", re.IGNORECASE),
    re.compile(
        r"\bcurrently\s+\*{0,2}(?:has|have|is|are|reports?|walks?|stands?|sits?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bclean at zero\b", re.IGNORECASE),
    re.compile(r"\bnow\s+(?:walks|reports|scans|stands at|sits at)\b", re.IGNORECASE),
)

_DATED = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\bas of \d{4}"
    r"|\bat (?:this|the) decision\b"
    r"|\bat the time\b"
    r"|\bon that date\b"
    r"|\bon the day this landed\b"
    r"|\bwhen this landed\b"
    r"|\bat this ADR\b",
    re.IGNORECASE,
)

_RATCHET_BASELINES = ROOT / "tooling" / "ratchet" / "baselines"


def _body_above_amendments(text: str) -> str:
    head, _, _ = text.partition(_AMENDMENTS_HEADING)
    return head


def _sentences(text: str) -> list[str]:

    flat = " ".join(text.split())
    return [s for s in re.split(r"(?<=[.;:])\s+|(?=\|)", flat) if s.strip()]


_ROOTED = ("odoo/", "tooling/", "addons/", "doc/", "crates/", ".github/")

_ROW_RE = re.compile(
    r"^\|\s*\[(\d{4})\]\(([^)]+)\)\s*\|\s*(.+?)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*"
    r"\|\s*(.+?)\s*\|\s*$",
    re.MULTILINE,
)
_H1_RE = re.compile(r"^#\s*ADR-(\d{4}):\s*(.+?)\s*$", re.MULTILINE)
_STATUS_RE = re.compile(r"^-\s*\*\*Status:\*\*\s*(.+?)\s*$", re.MULTILINE)
_DATE_RE = re.compile(r"^-\s*\*\*Date:\*\*\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_PATH_RE = re.compile(r"`([^`]+)`")


_CORPUS_TREES = ("odoo", "addons", "tooling")

_ADDON_TREES = ("odoo/addons", "addons")

_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", re.MULTILINE)
_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.MULTILINE)
_MODEL_RE = re.compile(
    r"^\s*_(?:name|inherit)\s*=\s*[\"']([a-z][\w.]*)[\"']", re.MULTILINE
)

_CALL_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\(\)$")

_MODEL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]+)+$")

_SRC_SUFFIXES = (
    ".py",
    ".js",
    ".mjs",
    ".xml",
    ".md",
    ".rst",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".txt",
    ".sh",
    ".lock",
    ".scss",
    ".css",
)

_PROSE_CHARS = "<>*|{}, "

_LINE_REF_RE = re.compile(r":\d+(?:[-–]\d+)?$")


def _strip_line_ref(token: str) -> str:
    return _LINE_REF_RE.sub("", token)


_corpus_cache: dict[str, object] = {}


def _corpus() -> dict[str, object]:

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
            if module is not None:
                if not (module / tail).exists():
                    findings.append(("module-path", token))
            elif not (ROOT / "odoo" / token).exists():
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
    return status.split(maxsplit=1)[0] if status else ""


def is_unbuilt(text: str) -> bool:

    status = _STATUS_RE.search(text)
    return bool(status) and _status_kind(status.group(1)) in UNBUILT_STATUS_KINDS


def section_order(text: str) -> tuple[list[str], list[str]]:

    found = [s for s in _SECTION_RE.findall(text) if s in TEMPLATE_SECTION_ORDER]
    return found, sorted(found, key=TEMPLATE_SECTION_ORDER.index)


def _norm_title(title: str) -> str:

    return " ".join(title.replace("`", "").split())


def _index_rows() -> dict[str, tuple[str, str, str, str]]:
    return {
        m.group(1): (m.group(2), m.group(3), m.group(4), m.group(5))
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
        for number, (link, _title, _date, _status) in _index_rows().items():
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
        for number, (_link, title, _date, _status) in _index_rows().items():
            h1 = _H1_RE.search(_adr_text(number))
            self.assertIsNotNone(h1, f"ADR-{number} has no `# ADR-{number}:` heading")
            self.assertEqual(
                _norm_title(title),
                _norm_title(h1.group(2)),
                f"README title for {number} disagrees with the ADR heading",
            )

    def test_index_status_matches_the_adr_status_kind(self):
        for number, (_link, _title, _date, status) in _index_rows().items():
            m = _STATUS_RE.search(_adr_text(number))
            self.assertIsNotNone(m, f"ADR-{number} has no **Status:** line")
            self.assertEqual(
                _status_kind(status),
                _status_kind(m.group(1)),
                f"README status kind for {number} disagrees with the ADR",
            )

    def test_index_date_matches_the_adr_date(self):
        for number, (_link, _title, date, _status) in _index_rows().items():
            m = _DATE_RE.search(_adr_text(number))
            self.assertIsNotNone(m, f"ADR-{number} has no **Date:** line")
            self.assertEqual(
                date,
                m.group(1),
                f"README date for {number} disagrees with the ADR's **Date:** "
                f"line. The row restates the record; correct the row.",
            )

    def test_status_kind_is_known(self):

        for p in ADR_FILES:
            m = _STATUS_RE.search(p.read_text(encoding="utf-8"))
            self.assertIsNotNone(m, f"{p.name} has no **Status:** line")
            self.assertIn(
                _status_kind(m.group(1)),
                STATUS_KINDS,
                f"{p.name} carries an unknown status. The vocabulary is "
                f"{sorted(STATUS_KINDS)} — see doc/adr/README.md. Adding a "
                f"status means deciding here whether it is fact-checked.",
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

    def test_alternatives_are_required_from_the_cutoff_on(self):

        for p in ADR_FILES:
            if int(p.name[:4]) < ALTERNATIVES_REQUIRED_FROM:
                continue
            sections = set(_SECTION_RE.findall(p.read_text(encoding="utf-8")))
            self.assertIn(
                "Alternatives considered",
                sections,
                f"{p.name} is at or past ADR-"
                f"{ALTERNATIVES_REQUIRED_FROM:04d}, so it must carry an "
                f"'## Alternatives considered' section (see README.md's "
                f"template). If nothing else was genuinely on the table, say "
                f"that and why the space was that narrow.",
            )

    def test_template_sections_appear_in_template_order(self):

        for p in ADR_FILES:
            if int(p.name[:4]) < SECTION_ORDER_REQUIRED_FROM:
                continue
            found, expected = section_order(p.read_text(encoding="utf-8"))
            self.assertEqual(
                found,
                expected,
                f"{p.name} orders the template's sections {found}, but the "
                f"template's order is {list(TEMPLATE_SECTION_ORDER)}. Sections "
                f"of your own may go anywhere; these are the argument's spine.",
            )

    def test_withdrawn_records_say_why_in_an_amendment(self):

        for p in ADR_FILES:
            text = p.read_text(encoding="utf-8")
            status = _STATUS_RE.search(text)
            if not status or _status_kind(status.group(1)) != "Withdrawn":
                continue
            self.assertIn(
                "Amendments",
                set(_SECTION_RE.findall(text)),
                f"{p.name} is Withdrawn and carries no '## Amendments' section. "
                f"Say what withdrew it and why — the argument is the reason the "
                f"record is kept rather than deleted.",
            )

    def test_no_record_carries_an_implementation_status_section(self):

        for p in ADR_FILES:
            if int(p.name[:4]) < IMPLEMENTATION_STATUS_FORBIDDEN_FROM:
                continue
            self.assertNotIn(
                "Implementation status",
                set(_SECTION_RE.findall(p.read_text(encoding="utf-8"))),
                f"{p.name} carries an '## Implementation status' section. That "
                f"is a present-tense claim about the tree in a record that may "
                f"never be edited, so it can only decay. Put the state in "
                f"doc/architecture/, where it is re-derived, or date the "
                f"sentence so it stays true.",
            )

    def test_accepted_records_answer_the_enforcement_question(self):

        for p in ADR_FILES:
            if int(p.name[:4]) < ENFORCEMENT_ANSWER_REQUIRED_FROM:
                continue
            text = p.read_text(encoding="utf-8")
            status = _STATUS_RE.search(text)
            if not status or _status_kind(status.group(1)) != "Accepted":
                continue
            self.assertIn(
                "Enforcement",
                set(_SECTION_RE.findall(text)),
                f"{p.name} is Accepted and carries no '## Enforcement' section. "
                f"State what keeps the decision true, or state that nothing does "
                f"and why — silence is the one answer that is not allowed.",
            )


class TestUnbuiltExemptionProbes(unittest.TestCase):
    def test_probe_draft_is_unbuilt(self):
        self.assertTrue(is_unbuilt("- **Status:** Draft\n"))

    def test_probe_proposed_is_unbuilt(self):
        self.assertTrue(is_unbuilt("- **Status:** Proposed\n"))

    def test_probe_accepted_is_built(self):
        self.assertFalse(is_unbuilt("- **Status:** Accepted\n"))

    def test_probe_qualified_accepted_is_built(self):
        self.assertFalse(is_unbuilt("- **Status:** Accepted (steps 1–3 done)\n"))

    def test_probe_superseded_is_built(self):
        self.assertFalse(is_unbuilt("- **Status:** Superseded by ADR-0001\n"))

    def test_probe_a_statusless_document_is_built(self):
        self.assertFalse(is_unbuilt("# Architecture Decision Records\n"))


class TestSectionOrderProbes(unittest.TestCase):
    def test_probe_template_order_is_quiet(self):
        text = (
            "## Context\n## Decision\n## Alternatives considered\n"
            "## Consequences\n## Enforcement\n## Amendments\n"
        )
        found, expected = section_order(text)
        self.assertEqual(found, expected)

    def test_probe_the_adr_0016_shape_is_caught(self):
        text = (
            "## Context\n## Decision\n## Consequences\n"
            "## Alternatives considered\n## Enforcement\n"
        )
        found, expected = section_order(text)
        self.assertNotEqual(found, expected)

    def test_probe_bespoke_sections_do_not_affect_the_order(self):
        text = (
            "## Context\n## Decision\n"
            "## The consequence that needed handling: patch targets\n"
            "## Alternatives considered\n## Consequences\n## Enforcement\n"
        )
        found, expected = section_order(text)
        self.assertEqual(found, expected)
        self.assertNotIn("The consequence that needed handling: patch targets", found)


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
        return [
            _strip_line_ref(token).rstrip("/")
            for token in _PATH_RE.findall(text)
            if token.startswith(_ROOTED) and not any(c in token for c in _PROSE_CHARS)
        ]

    def test_backticked_repo_paths_exist(self):
        for p in [*ADR_FILES, README_PATH]:
            text = p.read_text(encoding="utf-8")
            if is_unbuilt(text):
                continue
            for path in self._rooted_paths(text):
                self.assertTrue(
                    (ROOT / path).exists(),
                    f"{p.name} references `{path}`, which is not in the tree",
                )


class TestReferencedNamesExist(unittest.TestCase):
    _ADVICE = {
        "module-path": (
            "an addon-relative path that does not resolve under odoo/addons/ or "
            "addons/, and does not resolve as a core-package path under odoo/ "
            "either"
        ),
        "symbol": "a callable no def/class in the tree defines",
        "model": "a model name no _name/_inherit in the tree declares",
    }

    def test_every_adr_names_only_things_that_exist(self):
        for p in [*ADR_FILES, README_PATH]:
            text = p.read_text(encoding="utf-8")
            if is_unbuilt(text):
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
    def test_probe_a_addon_relative_path_is_caught(self):
        found = existence_findings("see `base/models/object_store.py` for this")
        self.assertEqual(found, [("module-path", "base/models/object_store.py")])

    def test_probe_b_rooted_path_is_still_caught(self):
        self.assertFalse((ROOT / "odoo/db/does_not_exist.py").exists())

    def test_probe_e_core_package_shorthand_path_is_caught(self):
        found = existence_findings("see `orm/fields/does_not_exist.py` for this")
        self.assertEqual(found, [("module-path", "orm/fields/does_not_exist.py")])

    def test_probe_f_real_core_package_shorthand_path_is_quiet(self):
        found = existence_findings("see `orm/fields/relational/many2one.py` for this")
        self.assertEqual(found, [])

    def test_probe_c_symbol_in_an_existing_file_is_caught(self):
        found = existence_findings("`Cursor.totally_fake_method()` in a real file")
        self.assertEqual(found, [("symbol", "Cursor.totally_fake_method()")])

    def test_probe_d_absent_model_name_is_caught(self):
        found = existence_findings("one row per copy: `ir.content.placement`")
        self.assertEqual(found, [("model", "ir.content.placement")])

    def test_real_references_do_not_fire(self):
        quiet = (
            "`base/models/ir_attachment.py` and `odoo/orm/components/core.py`, "
            "`is_maintenance_db()`, `Environment.ref()`, `ir.attachment`, "
            "`odoo.orm.runtime`, `env.cache`, `transaction.storage`, "
            "`odoo/libs/<area>`, `odoo/orm|db|libs`, "
            "`tooling/ratchet/baselines/{ruff,mypy}.json`"
        )
        self.assertEqual(existence_findings(quiet), [])


def live_status_findings(text: str) -> list[str]:
    found = []
    for sentence in _sentences(_body_above_amendments(text)):
        if _DATED.search(sentence):
            continue
        if any(rx.search(sentence) for rx in _LIVE_STATUS_RES):
            found.append(sentence.strip())
    return found


class TestNoLiveStatusClaims(unittest.TestCase):
    def test_no_adr_asserts_a_live_status(self):
        for p in ADR_FILES:
            found = live_status_findings(p.read_text(encoding="utf-8"))
            self.assertEqual(
                found,
                [],
                f"{p.name} asserts a live status or count in an immutable "
                f"record. Date it ('at this decision', 'measured … on "
                f"YYYY-MM-DD') or cite the source of truth "
                f"(tooling/ratchet/baselines/, layer_check.py's CONTRACTS, or "
                f"'run the checker') instead: {found}",
            )

    def test_no_adr_restates_a_current_ratchet_floor(self):

        floors = {}
        for path in sorted(_RATCHET_BASELINES.glob("*.json")):
            count = json.loads(path.read_text(encoding="utf-8"))["count"]
            if count:
                floors[path.stem] = count
        self.assertTrue(floors, "no ratchet baselines found — gate would be vacuous")

        for p in ADR_FILES:
            body = _body_above_amendments(p.read_text(encoding="utf-8"))
            for line in body.splitlines():
                for gate, count in floors.items():
                    if gate in line.lower() and re.search(rf"\b{count}\b", line):
                        self.fail(
                            f"{p.name} restates {gate}'s CURRENT ratchet floor "
                            f"({count}) beside the gate name: {line.strip()!r}. "
                            f"Cite tooling/ratchet/baselines/{gate}.json instead "
                            f"— a floor written into an immutable record is one "
                            f"the ratchet will move out from under."
                        )

    def test_probe_a_zero_floor_would_false_positive_on_a_version_string(self):

        self.assertRegex("the pinned tools (mypy 1.19.1, ruff 0.15.2)", r"\b0\b")


class TestLiveStatusProbes(unittest.TestCase):
    def test_probe_undated_clean_at_zero_is_caught(self):
        found = live_status_findings("Contract `x` (currently **clean at zero**).")
        self.assertEqual(len(found), 1, found)

    def test_probe_undated_now_walks_is_caught(self):
        self.assertEqual(
            len(live_status_findings("The checker now walks 6,069 files.")), 1
        )

    def test_probe_a_dated_measurement_is_allowed(self):
        quiet = "Measured 2074 on 2026-06-25, against a floor of 1972."
        self.assertEqual(live_status_findings(quiet), [])

    def test_probe_at_this_decision_is_allowed(self):
        quiet = "At this decision the core has **zero** tolerated exceptions."
        self.assertEqual(live_status_findings(quiet), [])

    def test_probe_amendments_are_exempt(self):
        text = (
            "## Enforcement\n\nContract `x`.\n\n"
            "## Amendments\n\n### 2026-08-07 — fixed\n\n"
            'It said "currently **clean at zero**", which could only decay.\n'
        )
        self.assertEqual(live_status_findings(text), [])

    def test_probe_ordinary_prose_does_not_fire(self):
        quiet = (
            "The ORM is organised as four layers. `libs/` is dependency-free, "
            "and the gate is drift-zero — no `odoo.*` import may be added. "
            "Run the checker for the contract's live status."
        )
        self.assertEqual(live_status_findings(quiet), [])


if __name__ == "__main__":
    unittest.main()
