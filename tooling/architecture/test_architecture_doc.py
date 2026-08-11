#!/usr/bin/env python3
"""Fact-check ``doc/architecture/ARCHITECTURE.md`` against the code it describes.

``ARCHITECTURE.md`` opens by claiming it is *enforced*. That was true of the
dependency rules — ``layer_check.py`` runs them — and false of everything else on
the page: the counts, the module inventories, the ADR references, the command
lines. Those drifted silently, because nothing read the prose. A fact-check of
the page in 2026-08 found the drift is not hypothetical:

* it claimed ``BaseModel`` is composed from **18** mixins; the class has taken
  **21** bases since the ``_Properties``/``_MagicFields``/``_ModelMetadata``
  split, and the stale 18 had already been copied into
  ``.github/workflows/architecture.yml`` and ``mixin_coupling_check.py``;
* it claimed ``core-does-not-depend-on-addons`` ships **2** pinned entries, while
  every report prints **8** (2 ``KNOWN_VIOLATIONS`` rules × 4 call sites × 2
  granularities) — a reader comparing page to output cannot tell a real
  regression from the documented state;
* it drew the HTTP lifecycle through ``Model.retrying``, which does not exist:
  ``retrying()`` moved to ``odoo/service/transaction.py`` in this fork.

Each case is a *number or name stated in prose that the code also states*. So
each is mechanically checkable, and that is all this suite does — it never
re-derives architecture, it only asserts the two statements agree. A claim
neither side states (e.g. "components/ is unit-testable") is out of scope by
construction.

Run directly (``python tooling/architecture/test_architecture_doc.py``) or under
pytest; the ``Architecture Boundaries`` workflow runs the whole directory.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import layer_check
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="test_architecture_doc")

#: The architecture documentation is one document in several files: a front door
#: (context, forces, mechanisms, view index) plus the views it indexes. Every
#: assertion below is about *the documentation*, not about which file a sentence
#: currently sits in — so ``DOC`` is their concatenation, and content may be
#: moved between them without touching this suite. Splitting it that way is the
#: whole point: a page organised around what a checker can verify drifts toward
#: describing its own compliance instead of the system.
#:
#: Order is front door first, then the views in reading order, so a ``--verbose``
#: diff is stable. ``DOC_PATH`` stays the front door: it is what
#: ``test_architecture_doc_is_not_vacuous`` re-reads as the control.
#:
#: All of it lives in one flat directory. The front door sat in ``odoo/`` until
#: 2026-08 — a package-scoped home for a repo-scoped document, which forced the
#: two halves to cite each other across directories and produced 15 broken
#: references that no gate was reading.
_ARCH_DOCS = ROOT / "doc" / "architecture"
DOC_PATH = _ARCH_DOCS / "ARCHITECTURE.md"
DOC_PATHS = (
    DOC_PATH,
    _ARCH_DOCS / "module.md",
    _ARCH_DOCS / "runtime.md",
    _ARCH_DOCS / "data.md",
    _ARCH_DOCS / "deployment.md",
    _ARCH_DOCS / "scenarios.md",
    _ARCH_DOCS / "gates.md",
    _ARCH_DOCS / "risks.md",
    _ARCH_DOCS / "qualities.md",
)
#: ``DOC_PATHS`` must be the directory, in both directions.
#:
#: A missing file was already an error. The *other* direction was not checked,
#: and it is the same hole that let ``orm/_protocols.py`` land feeding no gate:
#: a member absent from an inclusion list is not failed, it is **unmeasured**,
#: and an unmeasured page is indistinguishable from a clean one. A new view
#: added here would have been pinned by nothing.
_on_disk = {p.name for p in _ARCH_DOCS.glob("*.md")}
_listed = {p.name for p in DOC_PATHS}
if _on_disk != _listed:
    raise AssertionError(
        f"DOC_PATHS and doc/architecture/ disagree — missing from the suite: "
        f"{sorted(_on_disk - _listed)}; listed but absent from disk: "
        f"{sorted(_listed - _on_disk)}. This suite pins the whole set, so "
        f"either is a broken gate rather than a lighter one."
    )


def read_docs() -> str:
    """The whole architecture document, re-read from disk.

    ``test_architecture_doc_is_not_vacuous`` needs this: its control run must
    compare against exactly what this suite reads, and reading ``DOC_PATH``
    alone would only be the front door.
    """
    return "\n\n".join(p.read_text(encoding="utf-8") for p in DOC_PATHS)


DOC = read_docs()

#: ``DOC`` with every run of whitespace collapsed to one space. Use this for any
#: assertion on a prose *sentence*: the source is hard-wrapped at 80 columns, so
#: re-flowing a paragraph moves the newlines and would fail a raw ``assertIn``
#: without changing a word. Structural assertions (table rows, fenced blocks,
#: deliberate line breaks) stay on ``DOC``.
DOC_FLAT = " ".join(DOC.split())


def _class_bases(source: Path, class_name: str) -> list[str]:
    """Return the direct base-class names of ``class_name``, by AST.

    Parsed rather than imported: this suite is stdlib-only and must run in the
    boundary-gate job, which installs pytest and nothing else — importing
    ``odoo.orm`` there would need the full dependency set.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [b.id for b in node.bases if isinstance(b, ast.Name)]
    raise AssertionError(f"class {class_name} not found in {source}")


def _imported_modules(source: Path) -> set[str]:
    """Return every dotted module name ``source`` imports, at any nesting."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


#: Number words the architecture documents spell out, so an assertion can
#: re-derive the figure rather than trust it. Shared by every test here that
#: compares a written-out count against a measured one -- it was a local dict
#: inside one test until a second test needed it.
NUMBER_WORDS = {
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "twenty-one": 21,
    "twenty-two": 22,
    "twenty-three": 23,
    "twenty-four": 24,
    "twenty-five": 25,
    "twenty-six": 26,
    "twenty-seven": 27,
    "twenty-eight": 28,
    "twenty-nine": 29,
    "thirty": 30,
    "thirty-one": 31,
    "thirty-two": 32,
    "thirty-three": 33,
}

#: The same map, value -> word, for the assertions that go the other way: they
#: measure a count and then look for its written form on the page. Derived
#: rather than written twice -- three separate local copies of this drifted out
#: of range within one session as gates were added, each failing with a bare
#: ``KeyError`` that read like a broken test rather than a grown tree.
NUMBER_WORD_BY_VALUE = {value: word for word, value in NUMBER_WORDS.items()}


class TestMixinCount(unittest.TestCase):
    """The two mixin counts in the prose must equal ``BaseModel``'s bases."""

    def setUp(self) -> None:
        self.bases = _class_bases(
            ROOT / "odoo" / "orm" / "models" / "base.py", "BaseModel"
        )

    def test_subsystem_map_count(self) -> None:
        match = re.search(r"BaseModel \+ (\d+) mixins", DOC)
        self.assertIsNotNone(match, "subsystem map no longer states a mixin count")
        self.assertEqual(
            int(match.group(1)),
            len(self.bases),
            "ARCHITECTURE.md's subsystem map disagrees with BaseModel.__bases__",
        )

    def test_coupling_section_count(self) -> None:
        match = re.search(r"composed from (\d+)\n?`?`?__slots__", DOC)
        self.assertIsNotNone(match, "coupling section no longer states a mixin count")
        self.assertEqual(int(match.group(1)), len(self.bases))

    def test_public_private_split(self) -> None:
        """The prose splits the count into public + private; check both halves."""
        match = re.search(r"— (\d+) public .*? plus (\d+) private", DOC, re.DOTALL)
        self.assertIsNotNone(match, "coupling section no longer states the split")
        public, private = int(match.group(1)), int(match.group(2))
        self.assertEqual(public, sum(not b.startswith("_") for b in self.bases))
        self.assertEqual(private, sum(b.startswith("_") for b in self.bases))
        self.assertEqual(public + private, len(self.bases))

    def test_unit_count_and_read_group_share(self) -> None:
        """The 26 file-level units, and how many ``read_group/`` contributes.

        Both numbers are stated in the same sentence and both were wrong at
        different times — the count is what ``mixin_coupling_check`` reports,
        the share is a directory listing.
        """
        import mixin_coupling_check as mcc

        units = mcc.collect_units()
        match = re.search(r"units — (\d+), since `read_group/` contributes (\w+)", DOC)
        self.assertIsNotNone(match, "the unit count sentence changed shape")
        words = {"three": 3, "four": 4, "five": 5, "six": 6}
        self.assertEqual(int(match.group(1)), len(units))
        self.assertEqual(
            words[match.group(2)],
            sum(name.startswith("read_group/") for name in units),
        )

    def test_named_boundary_mixins_are_the_real_first_and_last(self) -> None:
        match = re.search(r"\(`(\w+)` …\s*\n?\s*`(\w+)`\)", DOC)
        self.assertIsNotNone(match, "coupling section no longer names the range")
        public = [b for b in self.bases if not b.startswith("_")]
        self.assertEqual(match.group(1), public[0])
        self.assertEqual(match.group(2), public[-1])


class TestCountsRestatedElsewhere(unittest.TestCase):
    """The same counts, wherever else they are written down.

    This is the class that addresses how the drift actually happened. The mixin
    count was not wrong in one place — it was written in ``ARCHITECTURE.md``,
    copied into ``mixin_coupling_check.py``'s docstring, copied again into the
    workflow comment that explains why that gate exists, and restated as a
    fan-in table in ``_metadata.py``. Fixing the page alone would have left
    three files still saying 18, and the next reader would have believed
    whichever they opened first.

    So every restatement is checked against the same source of truth. Adding a
    fourth copy is fine; leaving it unchecked is what is not.
    """

    def setUp(self) -> None:
        self.bases = _class_bases(
            ROOT / "odoo" / "orm" / "models" / "base.py", "BaseModel"
        )

    #: The shapes a restated mixin count takes today. A new phrasing elsewhere
    #: needs a pattern here — that is the cost of writing the number down again.
    COUNT_PATTERNS = (
        r"(\d+) ``__slots__ = \(\)`` mixins",
        r"BaseModel's (\d+) mixins",
    )

    def _mixin_counts_in(self, rel: str) -> list[int]:
        """Every "N mixins"-shaped number in a file."""
        text = (ROOT / rel).read_text(encoding="utf-8")
        return [
            int(n) for pattern in self.COUNT_PATTERNS for n in re.findall(pattern, text)
        ]

    def test_checker_docstring(self) -> None:
        counts = self._mixin_counts_in("tooling/architecture/mixin_coupling_check.py")
        self.assertTrue(counts, "mixin_coupling_check.py no longer states the count")
        for count in counts:
            self.assertEqual(count, len(self.bases))

    def test_workflow_comment(self) -> None:
        counts = self._mixin_counts_in(".github/workflows/architecture.yml")
        self.assertTrue(counts, "architecture.yml no longer states the count")
        for count in counts:
            self.assertEqual(count, len(self.bases))

    def test_metadata_fan_in_figures(self) -> None:
        """``_metadata.py`` quantifies its own fan-in; re-derive every number.

        These are the reason the module exists (the metadata fan-in that put
        ``base.py`` in a nine-unit cycle), so a stale figure undercuts the
        rationale, not just a detail.
        """
        import mixin_coupling_check as mcc

        units = mcc.collect_units()
        doc = (ROOT / "odoo" / "orm" / "models" / "mixins" / "_metadata.py").read_text(
            encoding="utf-8"
        )
        docstring = ast.get_docstring(ast.parse(doc)) or ""
        flat = " ".join(docstring.split())

        total = re.search(r"(\d+) of them, this module plus (\d+) others", flat)
        self.assertIsNotNone(total, "the unit-count framing changed shape")
        self.assertEqual(int(total.group(1)), len(units))
        self.assertEqual(int(total.group(2)), len(units) - 1)

        readers = {
            attr: sum(
                attr in unit.uses for name, unit in units.items() if name != "_metadata"
            )
            for attr in ("_fields", "_name", "_table", "pool")
        }
        stated = dict(
            zip(
                ("_fields", "_name", "_table", "pool"),
                (
                    int(n)
                    for n in re.findall(
                        r"is read by (\d+), ``self\._name`` by (\d+), "
                        r"``self\._table`` by (\d+) and ``self\.pool`` by (\d+)",
                        flat,
                    )[0]
                ),
                strict=True,
            )
        )
        self.assertEqual(stated, readers)

    def test_metadata_call_site_figures(self) -> None:
        """The "don't change how these are reached" figures must re-measure.

        These were the one set of numbers on the page that no reading could
        reproduce: the docstring claimed 528 ``self._name`` sites and 436
        ``self._fields`` across ``odoo/addons`` + ``enterprise`` +
        ``agromarin``, where those three trees give 283 and 218, and adding
        this repo's own ``addons/`` gives 586 and 495. The stated pair sat
        between every candidate scope, so it could be neither confirmed nor
        refuted — the failure mode of a number quoted without its method.

        The rewrite states the scope (this repo's two addon trees, ``self.``
        -qualified reads) so the count is a claim rather than a decoration.
        Sibling repos are deliberately out of scope: CI checks out this repo
        alone, so a cross-repo figure could never be re-measured here — which
        is how the original went unchecked in the first place.
        """
        docstring = (
            ast.get_docstring(
                ast.parse(
                    (
                        ROOT / "odoo" / "orm" / "models" / "mixins" / "_metadata.py"
                    ).read_text(encoding="utf-8")
                )
            )
            or ""
        )
        flat = " ".join(docstring.split())
        match = re.search(
            r"``self\._name`` has (\d+) sites and ``self\._fields`` (\d+)", flat
        )
        self.assertIsNotNone(match, "the call-site sentence changed shape")

        measured = {}
        for attr in ("_name", "_fields"):
            pattern = re.compile(rf"self\.{attr}\b")
            measured[attr] = sum(
                len(pattern.findall(path.read_text(encoding="utf-8", errors="ignore")))
                for tree in ("odoo/addons", "addons")
                for path in (ROOT / tree).rglob("*.py")
            )
        self.assertEqual(
            {"_name": int(match.group(1)), "_fields": int(match.group(2))},
            measured,
        )


class TestPosture(unittest.TestCase):
    """The premise the whole page rests on: the monoliths are decomposed.

    Six files. Five are now packages or gone; ``service/server.py`` survives as
    a re-export facade. Every layering rule on the page exists because those
    files were split, so it is worth asserting rather than assuming.

    The list used to be read out of an ``Identity`` bullet. That section was
    prose restating what the tree already shows — the floors it also carried are
    now cited by constant in *Process boot* — so the names live here instead,
    and this became a check on the tree rather than on a sentence about it.
    """

    #: Each monolith and the package that replaced it, or ``None`` where the
    #: file survives as a thin re-export facade.
    #:
    #: Written as a mapping because the previous form — walk the six names,
    #: ``if not path.exists(): continue`` — skipped five of them. ``odoo/api.py``
    #: does not exist precisely BECAUSE it became ``odoo/api/``, so the check
    #: read the absence that proves the claim as a reason to assert nothing, and
    #: ``service/server.py`` was the only one it ever tested.
    REPLACEMENTS = {
        "models.py": "models",
        "fields.py": "fields",
        "api.py": "api",
        "http.py": "http",
        "sql_db.py": "db",
        "service/server.py": None,
    }

    def test_named_monoliths_are_no_longer_monoliths(self) -> None:
        for name, package in self.REPLACEMENTS.items():
            with self.subTest(monolith=name):
                path = ROOT / "odoo" / name
                if package is None:
                    # Survivors are allowed, but only as thin facades.
                    # server.py is 81 lines of re-exports; a monolith would be
                    # thousands.
                    self.assertTrue(path.is_file(), f"odoo/{name} is gone entirely")
                    lines = len(path.read_text(encoding="utf-8").splitlines())
                    self.assertLess(
                        lines, 400, f"odoo/{name} is {lines} lines — not a facade"
                    )
                    continue
                self.assertFalse(
                    path.exists(), f"odoo/{name} is back as a single module"
                )
                self.assertTrue(
                    (ROOT / "odoo" / package / "__init__.py").is_file(),
                    f"odoo/{name} was split into odoo/{package}/, which is not "
                    f"a package",
                )

    def test_sql_db_is_gone(self) -> None:
        """The db/ package replaced it outright, not alongside it."""
        self.assertFalse((ROOT / "odoo" / "sql_db.py").exists())
        self.assertTrue((ROOT / "odoo" / "db" / "__init__.py").is_file())


class TestOrmDocstringAgreesWithGate(unittest.TestCase):
    """``orm/__init__.py``'s layer listing vs ``layer_check.CONTRACTS``.

    ``ARCHITECTURE.md`` calls that docstring the statement of the layer model
    *in code*, which makes a disagreement between the two worse than a plain
    doc bug: a reader who opens the package instead of the page gets a
    different architecture. It listed ``_typing.py`` as cross-cutting while the
    ``orm-layer0-is-foundational`` contract scoped it to Layer 0, and omitted
    ``components/`` and ``_recordset.py`` entirely.
    """

    @classmethod
    def setUpClass(cls) -> None:
        src = (ROOT / "odoo" / "orm" / "__init__.py").read_text(encoding="utf-8")
        cls.docstring = ast.get_docstring(ast.parse(src)) or ""

    def _section(self, heading: str) -> str:
        """The indented block under ``heading``, up to the next blank-line gap."""
        body = self.docstring.split(heading, 1)[1]
        return body.split("\n\n", 1)[0]

    def test_layer0_section_matches_the_contract(self) -> None:
        contract = next(
            c for c in layer_check.CONTRACTS if c.name == "orm-layer0-is-foundational"
        )
        expected = {dotted.rsplit(".", 1)[-1] for dotted in contract.source}
        section = self._section("Layer 0 — Zero-dependency foundations:")
        listed = set(re.findall(r"^  (\w+)\.py", section, re.MULTILINE))
        self.assertEqual(
            expected,
            listed,
            "orm/__init__.py's Layer 0 listing and the layer-0 contract disagree",
        )

    def test_every_orm_member_is_documented(self) -> None:
        """No module or subpackage may be missing from the listing."""
        orm = ROOT / "odoo" / "orm"
        members = {p.stem for p in orm.glob("*.py") if p.stem != "__init__"}
        members |= {
            p.name
            for p in orm.iterdir()
            if p.is_dir() and (p / "__init__.py").exists() and p.name != "tests"
        }
        undocumented = {m for m in members if m not in self.docstring}
        self.assertEqual(
            set(),
            undocumented,
            f"orm/__init__.py's docstring does not mention: {sorted(undocumented)}",
        )

    def test_the_page_names_the_tie_breaker(self) -> None:
        """Two statements of one model need a stated winner.

        The page used to assert the two *agree* ("Both now name every member at
        the layer the gate enforces"), which is what this suite already proves
        module by module — and which stops being true for a moment every time
        someone edits one side. What the page has to carry instead is which
        side wins while they disagree.
        """
        self.assertIn(
            "Where a doc and the gate differ, `layer_check.py`'s `CONTRACTS` "
            "wins — it is the definition that runs.",
            DOC_FLAT,
        )


class TestCompositionTable(unittest.TestCase):
    """The five-composition table in ``module.md``, cell by cell.

    This replaces nine prose assertions with one table. The prose said things
    like "Registry's first run found a 3-unit cycle over 4 edges" -- true,
    dated, and unre-derivable, so an assertion could only pin it as *text*. Six
    of the numbers on the page were pinned that way, which is pinning the
    sentence rather than the fact.

    Every cell below is measured from a live ``mixin_coupling_check`` run
    instead. A row that drifts fails here, and the failure names the column.
    """

    #: ``module.md``'s table header, in order. Parsing by position rather than
    #: by name is deliberate: a reordered column would otherwise silently
    #: compare the wrong measurement against the wrong cell.
    COLUMNS = (
        "Composition",
        "Units",
        "Edges",
        "`cyclic_edges`",
        "`unowned_shared_state`",
        "Root dominates its leaves?",
    )

    @classmethod
    def setUpClass(cls) -> None:
        import mixin_coupling_check as mcc

        cls.mcc = mcc
        cls.rows = cls._parse_table()

    @staticmethod
    def _parse_table() -> dict[str, list[str]]:
        """``{label: [cells]}`` from the composition table in ``module.md``."""
        rows: dict[str, list[str]] = {}
        for line in DOC.splitlines():
            match = re.match(r"^\| `(\w+)` \(`[^`]+`\) \|(.+)\|$", line)
            if match:
                rows[match.group(1)] = [c.strip() for c in match.group(2).split("|")]
        return rows

    def _root_dominates(self, comp) -> bool:
        """Is the composition root larger than all its leaves put together?

        The shape claim the table's last column carries. Measured rather than
        tabulated as two line counts: the counts move on every edit to either
        file and say nothing the direction does not. Resolved by searching
        ``unit_dir`` for each unit's filename, because a unit may live in a
        subpackage (``read_group/sql.py``) while its recorded name is the bare
        stem.
        """
        units = self.mcc.collect_units(comp)
        root = len((comp.root_dir / comp.root_file).read_text().splitlines())
        mixins = 0
        for name, unit in units.items():
            if name == comp.root_file:
                continue
            for filename in unit.files:
                found = list(comp.unit_dir.rglob(Path(filename).name))
                self.assertTrue(found, f"{comp.label}: cannot locate {filename}")
                mixins += len(found[0].read_text().splitlines())
        return root > mixins

    def test_the_table_lists_every_measured_composition(self) -> None:
        """Neither side may carry a composition the other does not.

        The gate has been blind twice, both times to a composition nobody had
        written down. A row missing here is that failure mode returning.
        """
        self.assertEqual(
            sorted(c.label for c in self.mcc.COMPOSITIONS),
            sorted(self.rows),
            "the composition table and COMPOSITIONS disagree",
        )
        self.assertEqual(5, len(self.mcc.COMPOSITIONS))

    def test_the_table_header_is_the_one_this_test_parses(self) -> None:
        """Guards the positional parse above against a reordered column."""
        header = "| " + " | ".join(self.COLUMNS) + " |"
        self.assertIn(
            header,
            DOC,
            "the composition table's columns moved; this suite reads them by "
            "position, so update COLUMNS and the row assertions together",
        )

    def test_every_cell_re_derives(self) -> None:
        self.assertTrue(
            self.rows,
            "no composition rows parsed out of the document — the table is "
            "gone or its row shape changed, so this test would compare nothing",
        )
        for comp in self.mcc.COMPOSITIONS:
            with self.subTest(composition=comp.label):
                cells = self.rows[comp.label]
                measured = self.mcc.measure(comp=comp)
                expected = [
                    str(len(measured["units"])),
                    str(measured["edges_total"]),
                    str(measured["cyclic_edges"]),
                    str(measured["unowned_shared_state"]),
                    "**yes**" if self._root_dominates(comp) else "no",
                ]
                self.assertEqual(
                    expected,
                    cells,
                    f"{comp.label} row is stale",
                )

    def test_every_composition_is_a_dag_and_the_page_says_so(self) -> None:
        """``cyclic_edges`` 0 in every row is the DAG claim; assert both sides."""
        for comp in self.mcc.COMPOSITIONS:
            self.assertEqual(
                0,
                self.mcc.measure(comp=comp)["cyclic_edges"],
                f"{comp.label} is no longer a DAG",
            )
            self.assertEqual("0", self.rows[comp.label][2])

    def test_the_ratchet_backs_every_column_that_can_regress(self) -> None:
        """A number the page presents as held must actually be held."""
        for comp in self.mcc.COMPOSITIONS:
            for key in (
                "max_scc",
                "cyclic_edges",
                "scc_without_base",
                "unowned_shared_state",
            ):
                self.assertIn(key, comp.baseline, f"{comp.label} does not pin {key}")
            self.assertEqual(
                self.mcc.measure(comp=comp)["unowned_shared_state"],
                comp.baseline["unowned_shared_state"],
            )

    def test_unowned_shared_state_is_named_not_just_counted(self) -> None:
        """The page names the members behind each non-zero count.

        A bare integer is not actionable; the names are what tell a reader
        which state has no owner. Assert the page names them and that the gate
        still finds exactly those.
        """
        named = {
            "BaseModel": {"env", "_ids", "_prefetch_ids", "_log_access"},
            "Field": {"description_attrs"},
            "Cursor": {"_cnx", "_obj", "_thread", "_schema_cache", "_before_statement"},
        }
        self.assertTrue(
            self.rows, "the composition table is gone; nothing left to name"
        )
        for comp in self.mcc.COMPOSITIONS:
            if comp.label not in named:
                continue
            with self.subTest(composition=comp.label):
                live = set(self.mcc.unowned_shared_state(comp))
                self.assertEqual(named[comp.label], live)
                for member in named[comp.label]:
                    self.assertIn(f"`{member}`", DOC_FLAT)

    def test_basemodel_is_measured_on_two_graphs(self) -> None:
        """The recordset view must be strictly wider, and the page's delta right.

        Ratcheting a second graph proves nothing if it sees no more than the
        first. The page states the delta as an arithmetic claim (``104 → 112``)
        precisely so it can be re-derived rather than believed.
        """
        narrow = self.mcc.measure()
        wide = self.mcc.measure(through_recordsets=True)
        self.assertGreater(
            wide["edges_total"],
            narrow["edges_total"],
            "recordset-mediated calls are no longer being detected",
        )
        self.assertEqual(0, wide["cyclic_edges"], "a recordset cycle is back")
        self.assertEqual([], wide["sccs"])
        delta = wide["edges_total"] - narrow["edges_total"]
        self.assertIn(
            f"adds {delta} edges — {narrow['edges_total']} → {wide['edges_total']}",
            DOC_FLAT,
        )
        for key in ("max_scc", "cyclic_edges", "scc_without_base"):
            self.assertIn(f"recordset_{key}", self.mcc.BASELINE)
        self.assertIn("`recordset_max_scc` 1", DOC_FLAT)
        self.assertIn("`recordset_cyclic_edges` 0", DOC_FLAT)

    def test_only_basemodel_is_recordset_aware(self) -> None:
        """The page says the other four are ``self``-only; the gate must agree."""
        aware = {c.label for c in self.mcc.COMPOSITIONS if c.recordset_aware}
        self.assertEqual({"BaseModel"}, aware)

    def test_units_are_file_level_not_bases(self) -> None:
        """31 units against 26 bases — the page states why, so check the why."""
        units = self.mcc.collect_units()
        bases = _class_bases(ROOT / "odoo" / "orm" / "models" / "base.py", "BaseModel")
        self.assertGreater(len(units), len(bases))
        read_group = {n for n in units if n.startswith("read_group/")}
        self.assertEqual(
            {
                "read_group/_empty",
                "read_group/fill",
                "read_group/format",
                "read_group/mixin",
                "read_group/sql",
            },
            read_group,
        )
        self.assertIn("base.py", units)


class TestCompositionDesignRule(unittest.TestCase):
    """ "A leaf nothing depends on cannot close a cycle" — the rule, measured.

    The page states this as the design rule for new mixins and offers
    ``base.py`` as the worked result. Both halves are checkable: the leaves it
    names must have no out-edges, and the root it calls isolated must have
    neither in- nor out-edges, in both graphs.
    """

    @classmethod
    def setUpClass(cls) -> None:
        import mixin_coupling_check as mcc

        cls.mcc = mcc
        cls.units = mcc.collect_units()
        cls.edges, _ = mcc.build_edges(cls.units)

    def test_base_py_is_isolated_in_both_views(self) -> None:
        self.assertIn("in-degree 0, out-degree 0, in\nboth views", DOC)
        self.assertEqual(
            {}, self.edges.get("base.py", {}), "base.py gained an out-edge"
        )
        inbound = [n for n, t in self.edges.items() if "base.py" in t]
        self.assertEqual([], inbound, f"base.py gained in-edges from {inbound}")
        wide, _ = self.mcc.build_edges(self.units, through_recordsets=True)
        self.assertEqual({}, wide.get("base.py", {}))
        self.assertEqual([], [n for n, t in wide.items() if "base.py" in t])

    def test_the_query_fan_in_is_stated_and_named(self) -> None:
        """Five units, and the page names which five."""
        dependants = sorted(n for n, t in self.edges.items() if "_query" in t)
        self.assertEqual(
            ["read", "read_group/mixin", "read_group/sql", "recompute", "search"],
            dependants,
        )
        stated = re.search(r"(\w+) units depend on `_query`", DOC_FLAT)
        self.assertIsNotNone(stated, "the _query fan-in is no longer stated")
        self.assertEqual(NUMBER_WORDS[stated.group(1).lower()], len(dependants))
        for unit in dependants:
            self.assertIn(f"`{unit}`", DOC_FLAT)

    def test_the_field_compute_worked_example_still_holds(self) -> None:
        """``_field_compute`` must remain a leaf reaching what the page says.

        The example only teaches the rule while it stays true: the mixin has to
        be a leaf (nothing depends on it) and its own reaches have to be the
        ones named, or the "closes nothing" conclusion is unsupported.
        """
        self.assertIn("_FieldComputeMixin", DOC)
        reached = set(self.edges.get("_field_compute", {}))
        dependants = [n for n, t in self.edges.items() if "_field_compute" in t]
        self.assertEqual([], dependants, "_field_compute is no longer a leaf")
        for unit in reached:
            self.assertIn(f"`{unit}`", DOC_FLAT)

    def test_the_registry_leaves_are_leaves(self) -> None:
        measured = self.mcc.measure(comp=self.mcc.REGISTRY_COMPOSITION)
        edges = measured["_edges"]
        for leaf in ("_registry_models", "_registry_init_phase"):
            self.assertIn(leaf, measured["units"])
            self.assertEqual({}, edges.get(leaf, {}), f"{leaf} is no longer a leaf")

    def test_the_declaration_is_what_moves_the_graph(self) -> None:
        """The page rests the rule on ownership-by-class-body. Assert the
        annotation it points at is still bound where the leaf can own it."""
        registry_src = (
            self.mcc.ROOT / "odoo" / "orm" / "runtime" / "_registry_models.py"
        ).read_text(encoding="utf-8")
        self.assertIn("models: dict[str, type[BaseModel]]", registry_src)

    def test_discovery_finds_exactly_the_documented_set(self) -> None:
        """The gate's own discovery must agree with the table.

        This is the assertion that ends "found by a person, not a gate": a
        composition in the tree and absent from ``COMPOSITIONS`` fails here.
        """
        self.assertIn("discovers composition roots from the tree", DOC_FLAT)
        self.assertEqual(
            {"BaseModel", "Field", "Registry", "Request", "Cursor"},
            {c.root_class for c in self.mcc.COMPOSITIONS},
        )

    def test_the_documented_explain_example_demonstrates_an_edge(self) -> None:
        """A ``--explain A B`` in the docs must name a pair that has an edge.

        The example was ``--explain read search``, chosen when that was the
        cycle. After ``_query`` landed it printed "no edge read -> search" — a
        documented command whose output is the absence of the thing it
        illustrates.
        """
        # EVERY example, not just the first. ``re.search`` matched only the
        # BaseModel one, so the composition-scoped example beside it went
        # unchecked and reached the very state this test exists to prevent:
        # `--composition Field --explain _field_convert base.py` printed "no
        # edge" and exited 2, illustrating the absence of the thing it was
        # cited for, because the _FieldMetadataMixin extraction had removed
        # that edge. Each example is resolved against its own composition.
        examples = re.findall(
            r"mixin_coupling_check\.py (?:--composition (\w+) \\?\s*)?"
            r"--explain (\w+) ([\w.]+)",
            DOC,
        )
        self.assertTrue(examples, "the --explain examples are gone")
        for label, source, target in examples:
            with self.subTest(composition=label or "BaseModel", edge=(source, target)):
                if label:
                    comp = next(c for c in self.mcc.COMPOSITIONS if c.label == label)
                    measured = self.mcc.measure(comp=comp)
                    units, edges = measured["_units"], measured["_edges"]
                else:
                    units, edges = self.units, self.edges
                self.assertIn(source, units, f"--explain names unknown {source}")
                self.assertIn(target, units, f"--explain names unknown {target}")
                self.assertIn(
                    target,
                    edges.get(source, {}),
                    f"the documented example `--explain {source} {target}` has "
                    f"no edge to show; pick a pair that does",
                )

    def test_the_cursor_counters_have_an_owner(self) -> None:
        """The fix behind ``Cursor``'s row, not just its number.

        ``sql_from_log`` / ``sql_into_log`` / ``sql_log_count`` must be declared
        and initialised on ``_MetricsMixin``, or the 2-cycle is back whatever
        the count says.
        """
        db = self.mcc.ROOT / "odoo" / "db"
        metrics = (db / "metrics.py").read_text(encoding="utf-8")
        cursor = (db / "cursor.py").read_text(encoding="utf-8")
        for counter in ("sql_from_log", "sql_into_log", "sql_log_count"):
            self.assertIn(f"{counter}:", metrics, f"{counter} left _MetricsMixin")
        self.assertIn("def _init_metrics_state(self)", metrics)
        self.assertIn("self._init_metrics_state()", cursor)
        self.assertNotIn(
            "    sql_from_log: dict[str, tuple[int, float]]\n"
            "    sql_into_log: dict[str, tuple[int, float]]",
            cursor,
            "Cursor declares the counters again — that is the back-edge",
        )

    def test_the_override_surface_is_distinguished_from_the_composition(self) -> None:
        """``BaseString`` overrides N of ``Field``'s M cache methods.

        Both figures re-derived: the page carried "six of twelve", which no
        scoping of the two classes produces.
        """

        def cache_methods(path: Path, cls: str) -> set[str]:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == cls:
                    return {
                        m.name
                        for m in node.body
                        if isinstance(m, ast.FunctionDef) and "cache" in m.name
                    }
            raise AssertionError(f"{cls} not found in {path}")

        fields = ROOT / "odoo" / "orm" / "fields"
        field = cache_methods(fields / "base.py", "Field")
        base_string = cache_methods(fields / "textual.py", "BaseString")
        overridden = field & base_string
        self.assertIn(
            f"`BaseString` overrides {len(overridden)} of\n`Field`'s "
            f"{len(field)} cache methods",
            DOC,
        )


class TestToolsReachesTheRuntime(unittest.TestCase):
    """R2's 2026-08-09 widening: ``tools/`` reaches the runtime through ``env``.

    The number is re-derived rather than restated, like every other figure in
    the register. If the allowlist moves to a better owner this fails, which is
    the point — the paragraph would then be describing a reach that no longer
    exists.
    """

    # ``ROOT`` rather than ``parents[N]``: depth-independent, and it raises
    # instead of guessing if the marker is missing. Counting parents here is
    # what ``test_repo_root.test_no_tool_counts_parents_to_reach_the_checkout_root``
    # exists to reject, and it caught this line.
    SOURCE = ROOT / "odoo" / "tools" / "files.py"

    def test_the_reach_count_is_live(self) -> None:
        self.assertIn(
            "reaches `env.transaction.file_open_tmp_paths` — the `file_open()` "
            "sandbox allowlist — at 4 sites",
            DOC_FLAT,
        )
        sites = self.SOURCE.read_text(encoding="utf-8").count(
            "transaction.file_open_tmp_paths"
        )
        self.assertEqual(
            4,
            sites,
            f"risks.md R2 says 4 tools/ reaches into the transaction; "
            f"files.py has {sites}",
        )

    def test_the_import_contract_really_is_clean(self) -> None:
        """The half that makes it a risk rather than a violation.

        If ``files.py`` ever imports the runtime outright, this stops being an
        invisible reach and becomes a ``layer_check`` failure — a different and
        much better problem, but one that makes the paragraph wrong.
        """
        self.assertIn(
            "that contract is clean, because the reach arrives through `env` "
            "and produces no import edge",
            DOC_FLAT,
        )
        source = self.SOURCE.read_text(encoding="utf-8")
        for banned in ("from odoo.orm", "import odoo.orm"):
            self.assertNotIn(banned, source)


class TestToolsIsTheFacadeForLibs(unittest.TestCase):
    """Both façade figures must re-derive: the direct one and the real one.

    The page said **23** where ``tools/__init__.py`` imports **22** names from
    ``odoo.libs``, and stopped there — so the sentence measured one file's
    import statements and read as if it measured the façade. Following each
    exported name one hop into the submodule that supplies it gives **58**,
    more than half of ``__all__``, which is the figure the section's argument
    actually rests on.

    Resolved by import rather than by ``__module__``: ``html_escape`` is a
    re-exported ``markupsafe`` alias and ``single_email_re`` a compiled
    pattern, so a live-attribute sweep answers 56 and looks authoritative doing
    it. It is also why this test parses instead of importing — which it could
    not do here anyway, the boundary job installing pytest and nothing else.
    """

    TOOLS = ROOT / "odoo" / "tools"

    @staticmethod
    def _import_sources(tree: ast.Module) -> dict[str, str]:
        """``imported name -> the module it came from`` (relative kept as-is)."""
        sources: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                origin = "." * node.level + (node.module or "")
                for alias in node.names:
                    sources[alias.asname or alias.name] = origin
        return sources

    def _submodule(self, dotted: str) -> Path | None:
        stem = self.TOOLS / dotted.lstrip(".").replace(".", "/")
        for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
            if candidate.is_file():
                return candidate
        return None

    def setUp(self) -> None:
        tree = ast.parse((self.TOOLS / "__init__.py").read_text(encoding="utf-8"))
        self.exported = [
            elt.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) == "__all__" for t in node.targets)
            for elt in node.value.elts
        ]
        self.top = self._import_sources(tree)

    def test_the_export_total_is_live(self) -> None:
        self.assertIn(f"of its {len(self.exported)} `__all__` symbols", DOC_FLAT)

    def test_the_direct_reexport_count_is_live(self) -> None:
        direct = {
            n for n in self.exported if self.top.get(n, "").startswith("odoo.libs")
        }
        self.assertIn(
            f"re-exports **{len(direct)} of its {len(self.exported)} `__all__` "
            f"symbols straight from `odoo.libs`**",
            DOC_FLAT,
        )
        # The named examples must stay real, or the sentence illustrates nothing.
        for symbol in ("SQL", "float_round", "classproperty", "make_index_name"):
            self.assertIn(symbol, direct)

    def test_the_transitive_count_is_live(self) -> None:
        """The figure the section's argument rests on, one hop deep."""
        from_libs = set()
        for name in self.exported:
            origin = self.top.get(name, "")
            if origin.startswith("odoo.libs"):
                from_libs.add(name)
                continue
            if not origin.startswith("."):
                continue
            submodule = self._submodule(origin)
            if submodule is None:
                continue
            supplier = self._import_sources(
                ast.parse(submodule.read_text(encoding="utf-8"))
            )
            if supplier.get(name, "").startswith("odoo.libs"):
                from_libs.add(name)
        rest = len(self.exported) - len(from_libs)
        self.assertIn(
            f"**{len(from_libs)} of the {len(self.exported)} come from "
            f"`odoo.libs`**, the other {rest} arriving",
            DOC_FLAT,
        )
        self.assertGreater(
            len(from_libs),
            len(self.exported) // 2,
            "the section claims more than half the façade; it no longer is",
        )
        # The two the run-time sweep misattributes must still be in the set,
        # or the paragraph explaining the 56 is explaining nothing.
        self.assertLessEqual({"html_escape", "single_email_re"}, from_libs)


class TestLayerProse(unittest.TestCase):
    """The per-layer bullets must match what the packages actually import."""

    def _orm_imports(self, package: str) -> set[str]:
        pkg = ROOT / "odoo" / "orm" / package
        names: set[str] = set()
        for path in pkg.rglob("*.py"):
            if "tests" in path.relative_to(pkg).parts:
                continue
            names |= _imported_modules(path)
            # Relative imports resolve within odoo.orm; catch them textually,
            # since ``from ..components.recompute import X`` has level=2.
            names |= {
                f"odoo.orm.{m}"
                for m in re.findall(
                    r"^from \.+(\w+)", path.read_text(encoding="utf-8"), re.MULTILINE
                )
            }
        return names

    def test_the_table_admits_the_non_orm_imports(self) -> None:
        """Every layer imports odoo.tools & co; "only Layer 0" misled.

        The claim is now stated once for the whole table rather than per row,
        so it is asserted against every layer rather than against Layer 1's
        bullet.
        """
        self.assertIn(
            'The invariant at every layer is "nothing from the ORM above it", '
            'not "nothing from `odoo`": all four import `odoo.tools`, '
            "`odoo.libs` and `odoo.exceptions` freely.",
            DOC_FLAT,
        )
        for package in ("fields", "domain", "models", "runtime"):
            with self.subTest(package=package):
                self.assertTrue(
                    any(i.startswith("odoo.tools") for i in self._orm_imports(package)),
                    f"orm/{package} no longer imports odoo.tools; the "
                    f"whole-table claim needs narrowing",
                )

    def test_layer1_really_avoids_components(self) -> None:
        """The Layer-1 row's positive claim: it imports components/ nowhere."""
        self.assertIn("| Imports `components/` nowhere |", DOC)
        imports = self._orm_imports("fields") | self._orm_imports("domain")
        self.assertEqual(
            set(),
            {i for i in imports if "components" in i},
            "Layer 1 now imports orm/components; the bullet is wrong",
        )

    def test_layer2_components_dependency_is_named(self) -> None:
        """models/ does import components/; the bullet names the one edge."""
        self.assertIn("components.recompute.RecomputeScheduler", DOC_FLAT)
        src = (ROOT / "odoo" / "orm" / "models" / "mixins" / "recompute.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from ...components.recompute import RecomputeScheduler", src)

    def test_layer3_owns_the_component_instances(self) -> None:
        src = (ROOT / "odoo" / "orm" / "runtime" / "transaction.py").read_text(
            encoding="utf-8"
        )
        for cls in ("FieldCache", "ComputeEngine", "UnitOfWork", "OrmCore"):
            self.assertIn(f"`{cls}`", DOC, f"{cls} dropped from the Layer-3 bullet")
            self.assertIn(f"{cls}(", src, f"Transaction no longer constructs {cls}")


class TestContractTable(unittest.TestCase):
    """The rules table must list exactly the contracts the checker runs."""

    def _table_rows(self) -> list[str]:
        # Rows of the "Enforced dependency rules" table: | `name` | rule | status |
        section = DOC.split("## Enforced dependency rules", 1)[1]
        section = section.split("**The eight original boundaries", 1)[0]
        return re.findall(r"^\| `([a-z0-9-]+)` \|", section, re.MULTILINE)

    def test_names_match_checker(self) -> None:
        """Same *set*, not same order.

        The table is ordered for a reader (Layer 0 before Layer 1, façade before
        its mirror); ``CONTRACTS`` is ordered by when each rule landed. Pinning
        the order would make a reordering of either a CI failure with nothing
        behind it. What must not drift is the membership: a contract the checker
        runs but the page does not list is an unenforced-looking rule, and a row
        with no contract behind it is a rule nobody enforces.
        """
        rows = self._table_rows()
        self.assertEqual(len(rows), len(set(rows)), "duplicate row in the table")
        self.assertEqual(set(rows), {c.name for c in layer_check.CONTRACTS})

    #: The eight boundaries the page calls "original" — the set that shipped
    #: with ADR-0005, before ``core-does-not-depend-on-addons`` (2026-08) and
    #: before the intra-package tier contracts. Pinned by name rather than by
    #: count: once contracts are added over time, "the table minus one" stops
    #: identifying which eight the sentence is about, and a bare count silently
    #: accepts a *substitution* (drop one original, add one new) that the
    #: sentence would then be lying about.
    ORIGINAL_EIGHT = frozenset(
        {
            "libs-is-dependency-free",
            "db-is-orm-agnostic",
            "orm-components-are-pure-python",
            "orm-layer0-is-foundational",
            "orm-layer1-below-models-and-runtime",
            "orm-models-below-runtime",
            "orm-seams-stay-below-models-and-runtime",
            "facade-boundary",
        }
    )

    def test_stated_clean_count_matches_the_table(self) -> None:
        """The eight *original* boundaries must all still be listed and clean."""
        rows = self._table_rows()
        self.assertEqual(8, len(self.ORIGINAL_EIGHT))
        missing = self.ORIGINAL_EIGHT - set(rows)
        self.assertFalse(
            missing, f"original boundary dropped from the table: {missing}"
        )
        self.assertIn("**The eight original boundaries are clean at zero**", DOC)

    def test_later_contracts_are_also_in_the_table(self) -> None:
        """Contracts added after the original eight must not be undocumented.

        ``test_names_match_checker`` already pins set equality both ways; this
        states the intent separately so a future reader can see that the
        "eight original" sentence is about provenance, not about the table
        being capped at nine rows.
        """
        rows = set(self._table_rows())
        later = {c.name for c in layer_check.CONTRACTS} - self.ORIGINAL_EIGHT
        self.assertTrue(later, "expected contracts beyond the original eight")
        self.assertFalse(later - rows, f"undocumented contract(s): {later - rows}")

    def test_components_row_admits_the_libs_exception(self) -> None:
        """``components/`` really does import ``odoo.libs``; the row must say so."""
        contract = next(
            c
            for c in layer_check.CONTRACTS
            if c.name == "orm-components-are-pure-python"
        )
        self.assertIn("odoo.libs", contract.allow)
        row = next(
            line
            for line in DOC.splitlines()
            if line.startswith("| `orm-components-are-pure-python`")
        )
        self.assertIn("except `odoo.libs`", row)

    def test_layer0_row_lists_the_real_source_modules(self) -> None:
        contract = next(
            c for c in layer_check.CONTRACTS if c.name == "orm-layer0-is-foundational"
        )
        row = next(
            line
            for line in DOC.splitlines()
            if line.startswith("| `orm-layer0-is-foundational`")
        )
        for dotted in contract.source:
            self.assertIn(f"`{dotted.rsplit('.', 1)[-1]}`", row)


class TestPinnedViolations(unittest.TestCase):
    """Pinned-exception counts in the prose must match a real run."""

    @classmethod
    def setUpClass(cls) -> None:
        _new, cls.known = layer_check.check()

    def test_rule_count(self) -> None:
        stated = re.search(r"\*\*two pinned `KNOWN_VIOLATIONS`\s*\n?rules\*\*", DOC)
        self.assertIsNotNone(stated, "the pinned-rule count is no longer stated")
        self.assertEqual(2, len(layer_check.KNOWN_VIOLATIONS))

    def test_reported_edge_count(self) -> None:
        match = re.search(r"expands to \*\*(\d+) tolerated edges\*\*", DOC)
        self.assertIsNotNone(match, "the tolerated-edge count is no longer stated")
        self.assertEqual(
            int(match.group(1)),
            len(self.known),
            "ARCHITECTURE.md states a different tolerated-edge count than "
            "layer_check.check() reports",
        )

    def test_no_new_violations(self) -> None:
        """The page says the boundaries are clean; a run must agree."""
        new, _known = layer_check.check()
        self.assertEqual([], new, "ARCHITECTURE.md claims 0 new violations")

    def test_pinned_rules_are_scoped_to_service(self) -> None:
        """The prose scopes the exceptions to ``odoo.service``."""
        self.assertIn("scoped to `odoo.service`", DOC_FLAT)
        for known in layer_check.KNOWN_VIOLATIONS:
            self.assertEqual("odoo.service", known.module)

    def test_tests_exemption_is_documented(self) -> None:
        """``odoo.tests`` is exempt from the addon contract; the page says so."""
        self.assertIn("CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT", DOC_FLAT)
        self.assertEqual(
            {"tests"}, set(layer_check.CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT)
        )

    def test_test_files_are_really_skipped(self) -> None:
        """The page warns that ``✅ clean`` excludes tests. Verify it does."""
        self.assertIn("Test files are not scanned", DOC_FLAT)
        self.assertTrue(layer_check._is_test_file(Path("odoo/orm/tests/test_x.py")))
        self.assertTrue(layer_check._is_test_file(Path("odoo/db/conftest.py")))
        self.assertFalse(layer_check._is_test_file(Path("odoo/db/pool.py")))


class TestRuntimeFloors(unittest.TestCase):
    """Python / PostgreSQL floors must match ``odoo/release.py``."""

    @classmethod
    def setUpClass(cls) -> None:
        src = (ROOT / "odoo" / "release.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        cls.consts: dict[str, object] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                with __import__("contextlib").suppress(ValueError):
                    cls.consts[node.target.id] = ast.literal_eval(node.value)

    def test_python_floor(self) -> None:
        """The page names the constant; ``init.py`` is what enforces it.

        It used to restate the value too — "Python 3.14 (`MIN_PY_VERSION` =
        `MAX_PY_VERSION` = 3.14)" — and this test policed the restatement. That
        is the second copy `doc/adr/README.md` forbids in as many words ("never
        restate a number that lives somewhere else; cite the file, not the
        value"), and it bought nothing: the digits were only ever correct
        because a test compared them to `release.py`, which is where a reader
        can look anyway. So the pinning moved to the pair that must agree —
        the constant and the code that raises on it.
        """
        self.assertEqual(self.consts["MIN_PY_VERSION"], self.consts["MAX_PY_VERSION"])
        self.assertIn("`MIN_PY_VERSION`", DOC)
        init = (ROOT / "odoo" / "init.py").read_text(encoding="utf-8")
        self.assertIn("if sys.version_info[:2] < MIN_PY_VERSION:", init)

    def test_postgres_floor(self) -> None:
        """Same shape, for the floor the connect path owns."""
        self.assertIsInstance(self.consts["MIN_PG_VERSION"], int)
        self.assertIn("`MIN_PG_VERSION`", DOC)
        self.assertIn("`PoolError`", DOC)
        pool = (ROOT / "odoo" / "db" / "pool.py").read_text(encoding="utf-8")
        self.assertIn("from odoo.release import MIN_PG_VERSION", pool)
        self.assertIn("raise PoolError(", pool.split("sv < MIN_PG_VERSION")[1])


class TestReferencedArtifacts(unittest.TestCase):
    """Every ADR, script and module path named on the page must exist."""

    def test_adrs_exist(self) -> None:
        adr_dir = ROOT / "doc" / "adr"
        numbers = sorted(set(re.findall(r"ADR-(\d{4})", DOC)))
        # Without this the test is a no-op the moment the citations or the
        # pattern change: "every ADR the page names exists" is trivially true of
        # a page that names none. Audited by running the suite against an empty
        # DOC -- this was one of four tests that survived it.
        self.assertTrue(numbers, "the page cites no ADR; the pattern has rotted")
        for number in numbers:
            self.assertTrue(
                list(adr_dir.glob(f"{number}-*.md")),
                f"ARCHITECTURE.md references ADR-{number}, which does not exist",
            )

    def test_adr_range_is_complete(self) -> None:
        """The closing ADR range on the page must cover every accepted ADR.

        The page writes the range with an en dash; the pattern below matches
        that character literally, so the docstring avoids repeating it (ruff's
        ambiguous-unicode check flags it in prose but not in a regex literal).
        """
        match = re.search(r"architecture decisions, (\d{4})–(\d{4})", DOC)
        self.assertIsNotNone(match, "the ADR range is no longer stated")
        on_disk = sorted(
            p.name[:4] for p in (ROOT / "doc" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md")
        )
        self.assertEqual((match.group(1), match.group(2)), (on_disk[0], on_disk[-1]))

    def test_documented_commands_exist(self) -> None:
        scripts = re.findall(r"^python (\S+\.py)", DOC, re.MULTILINE)
        self.assertTrue(
            scripts, "the page documents no command; the pattern has rotted"
        )
        for script in scripts:
            self.assertTrue(
                (ROOT / script).is_file(),
                f"ARCHITECTURE.md documents `python {script}`, which is missing",
            )

    def test_referenced_workflows_exist(self) -> None:
        workflows = re.findall(r"`\.github/workflows/([\w.-]+\.yml)`", DOC)
        self.assertTrue(
            workflows, "the page references no workflow; the pattern has rotted"
        )
        for wf in workflows:
            self.assertTrue((ROOT / ".github" / "workflows" / wf).is_file(), wf)

    def test_ci_gate_table_matches_the_workflow(self) -> None:
        """The gate table must be exactly the checkers ``architecture.yml`` runs.

        The count in the prose is stated separately from the table, and drifted
        the moment ``subsystem_map_check.py`` was added: the page still said
        "five", then said "six" while calling ``cross_repo_coherence.py`` the
        sixth. Both are derived here instead of trusted.
        """
        workflow = (ROOT / ".github" / "workflows" / "architecture.yml").read_text(
            encoding="utf-8"
        )
        run_in_ci = set(re.findall(r"python tooling/architecture/(\w+\.py)", workflow))
        section = DOC.split("## Quality gates beyond the boundaries", 1)[1]
        tabled = set(re.findall(r"^\| `(\w+\.py)` \|", section, re.MULTILINE))
        self.assertEqual(tabled, run_in_ci)

        stated = re.search(r"workflow runs \*\*([\w-]+)\*\* blocking checkers", DOC)
        self.assertIsNotNone(stated, "the gate count is no longer stated")
        self.assertEqual(NUMBER_WORDS[stated.group(1)], len(run_in_ci))

    def test_ci_path_filter_covers_every_scanned_tree(self) -> None:
        """A PR touching a scanned package must actually trigger this gate.

        The ``pull_request: paths:`` filter used to enumerate the core packages
        by hand, which is a second copy of every checker's scope and rots the
        same way prose does. Measured, four real packages inside the checkers'
        scope were missing from it -- ``odoo/api``, ``odoo/fields``,
        ``odoo/models`` and ``odoo/tests`` -- so a PR touching only those ran no
        gate on the PR at all, and drift was caught (if ever) by the post-merge
        ``push:`` trigger, after the merge-blocking check had reported nothing.

        This derives the requirement from the tree instead of trusting the list.
        """
        workflow = (ROOT / ".github" / "workflows" / "architecture.yml").read_text(
            encoding="utf-8"
        )
        pr_block = workflow.split("pull_request:", 1)[1].split("permissions:", 1)[0]
        globs = re.findall(r"^\s*- '([^']+)'", pr_block, re.MULTILINE)
        self.assertTrue(globs, "the pull_request path filter is empty")

        # NOT fnmatch: Python's `*` crosses `/` (`fnmatch("odoo/api/x.py",
        # "odoo/*.py")` is True), so an fnmatch-based version of this test
        # passes against the very filter it is meant to reject. GitHub's
        # semantics are `*` = any run of non-slash, `**` = any run including
        # slash, `**/` = zero or more directories.
        def to_regex(glob: str) -> re.Pattern[str]:
            out, i = [], 0
            while i < len(glob):
                if glob.startswith("**/", i):
                    out.append("(?:.*/)?")
                    i += 3
                elif glob.startswith("**", i):
                    out.append(".*")
                    i += 2
                elif glob[i] == "*":
                    out.append("[^/]*")
                    i += 1
                elif glob[i] == "?":
                    out.append("[^/]")
                    i += 1
                else:
                    out.append(re.escape(glob[i]))
                    i += 1
            return re.compile("^" + "".join(out) + "$")

        patterns = [to_regex(g) for g in globs]

        def covered(path: str) -> bool:
            return any(p.match(path) for p in patterns)

        uncovered: list[str] = []
        for tree in ("odoo", "addons"):
            root = ROOT / tree
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if child.name.startswith((".", "__")):
                    continue
                if child.is_dir():
                    if not any(child.rglob("*.py")):
                        continue
                    probe = f"{tree}/{child.name}/probe.py"
                elif child.suffix == ".py":
                    probe = f"{tree}/{child.name}"
                else:
                    continue
                if not covered(probe):
                    uncovered.append(probe)

        self.assertEqual(
            uncovered,
            [],
            "these scanned paths would not retrigger architecture.yml on a PR: "
            + ", ".join(uncovered),
        )

    def test_cross_repo_checker_is_a_prepush_hook(self) -> None:
        """It is outside CI on purpose; the page must describe where it does run."""
        self.assertIn("pre-commit install --hook-type pre-push", DOC_FLAT)
        config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        self.assertIn("cross_repo_coherence.py", config)
        self.assertIn("stages: [pre-push]", config)
        workflow = (ROOT / ".github" / "workflows" / "architecture.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(
            "python tooling/architecture/cross_repo_coherence.py",
            workflow,
            "cross_repo_coherence.py now runs in CI; the page says it does not",
        )

    def test_integration_gate_exclusions_are_stated(self) -> None:
        """ "runs the base suite" hid two excluded classes; both must be named."""
        workflow = (ROOT / ".github" / "workflows" / "integration_tests.yml").read_text(
            encoding="utf-8"
        )
        tags = re.search(r"TEST_TAGS: (\S+)", workflow)
        self.assertIsNotNone(tags, "integration_tests.yml no longer sets TEST_TAGS")
        excluded = re.findall(r"-:(\w+)", tags.group(1))
        self.assertTrue(excluded, "no exclusions left; simplify the prose")
        for name in excluded:
            self.assertIn(
                name, DOC, f"the base suite excludes {name}; the page does not say so"
            )

    @staticmethod
    def _gates_the_workflows_drive() -> set[str]:
        """Gate names actually piped into ``ratchet.py`` by a workflow."""
        driven: set[str] = set()
        for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
            driven.update(
                re.findall(
                    r"ratchet\.py (\w+) --count",
                    workflow.read_text(encoding="utf-8"),
                )
            )
        return driven

    def test_ratchet_baselines_match_documented_gates(self) -> None:
        """Three statements of one set: the page, the directory, the workflows.

        The first two were compared and the third was not, which leaves the
        inverse-direction hole this suite keeps finding: a baseline **no
        workflow drives** is not failed, it is inert, and inert is
        indistinguishable from held. ``ruff_docstring`` sat that way after
        pydocstyle was retired from ``ruff.toml`` and its step deleted from
        ``ruff.yml`` — a floor of 746 that nothing measured and nothing could
        move. Deriving the expected set from the workflows is what makes the
        next one fail instead of linger.
        """
        match = re.search(
            r"turns (\w+) tool\s+counts into one-way contracts: "
            r"\*\*([^*]+)\*\*",
            DOC,
        )
        self.assertIsNotNone(match, "the ratchet gate list is no longer stated")
        listed = {n.strip() for n in match.group(2).replace(" and ", ", ").split(",")}
        on_disk = {
            p.stem for p in (ROOT / "tooling" / "ratchet" / "baselines").glob("*.json")
        }
        driven = self._gates_the_workflows_drive()
        self.assertTrue(driven, "no workflow drives ratchet.py; the regex has rotted")
        self.assertEqual(
            driven,
            on_disk,
            "a baseline exists that no workflow drives, or a workflow drives a "
            "gate with no baseline",
        )
        self.assertEqual(listed, on_disk, "the page's gate list is stale")
        # The prose count is now captured too. It read "four" against a list of
        # eight for as long as this assertion has existed, because the regex
        # matched only the names -- a gate that pins a list and skips the number
        # beside it leaves exactly the drift it was written to stop.
        self.assertEqual(
            NUMBER_WORDS[match.group(1)],
            len(on_disk),
            "the ratchet gate list and the count in front of it disagree",
        )

    def test_named_source_paths_exist(self) -> None:
        """Backticked ``odoo/...`` and ``tooling/...`` paths must resolve.

        The page mixes two bases — ``tooling/...`` is repo-relative while
        ``libs/...``, ``addons/base/...`` etc. are relative to ``odoo/``, because
        that is the package the page is about. Both are tried, and a bare module
        name is allowed to resolve as ``<name>.py``. Globs are skipped.
        """
        pattern = r"`((?:odoo|tooling|doc|addons|libs|orm|db|http|service)/[\w./-]+?)`"
        found = sorted(set(re.findall(pattern, DOC)))
        self.assertTrue(found, "the page names no path; the pattern has rotted")
        for raw in found:
            if "*" in raw or raw.endswith("/"):
                continue
            candidates = [ROOT / raw, ROOT / "odoo" / raw]
            candidates += [c.with_suffix(".py") for c in list(candidates)]
            self.assertTrue(
                any(c.exists() for c in candidates),
                f"ARCHITECTURE.md names `{raw}`, which does not exist "
                f"(tried repo-relative and odoo/-relative)",
            )


class TestSubsystemMap(unittest.TestCase):
    """The subsystem map's module inventories must match the directories."""

    def _map_block(self) -> str:
        return DOC.split("## Subsystem map", 1)[1].split("```", 2)[1]

    def _modules_on_disk(self, package: str) -> set[str]:
        pkg = ROOT / "odoo" / package
        return {p.stem for p in pkg.glob("*.py") if p.stem != "__init__"} - {"tests"}

    def _listed_in(self, package: str, next_package: str) -> set[str]:
        """Names the map enumerates under ``package/``.

        Both kinds of annotation are stripped first, because neither names a
        module: ``(parenthesised prose)`` explains what a module does, and a
        ``[bracketed]`` label marks a grouping that is not a directory. What
        survives is the module list, plus the header line's own prose — so the
        header is dropped too.
        """
        block = self._map_block().split(f"── {package}/", 1)[1]
        block = block.split(f"── {next_package}/", 1)[0]
        body = block.split("\n", 1)[1]  # drop the header line's description
        # Innermost-out, because the prose nests: "_params (annotation-driven
        # @route(typed=True) coercion)". One non-greedy pass would consume up to
        # the inner ")" and leave "coercion)" looking like a module name.
        while True:
            stripped = re.sub(r"\([^()]*\)", " ", body)
            if stripped == body:
                break
            body = stripped
        body = re.sub(r"\[[^\]]*\]", " ", body)  # grouping labels
        return set(re.findall(r"[A-Za-z_]\w*", body))

    def _assert_inventory(self, package: str, next_package: str) -> None:
        listed = self._listed_in(package, next_package)
        on_disk = self._modules_on_disk(package)
        self.assertEqual(
            set(),
            on_disk - listed,
            f"odoo/{package}/ has modules the subsystem map omits: "
            f"{sorted(on_disk - listed)}",
        )
        self.assertEqual(
            set(),
            listed - on_disk,
            f"the subsystem map lists odoo/{package}/ modules that do not exist: "
            f"{sorted(listed - on_disk)}",
        )

    def test_db_inventory(self) -> None:
        self._assert_inventory("db", "http")

    def test_http_inventory(self) -> None:
        self._assert_inventory("http", "service")

    def test_flat_packages_are_declared_flat(self) -> None:
        """The map indents db/ and http/ groupings; the notation must say why.

        ``[brackets]`` is the whole reason those indented rows are not read as
        paths — by this suite, by ``subsystem_map_check.py``, and by a human.
        If either package ever grows a real subpackage the convention stops
        being true and the note becomes the misleading part.
        """
        self.assertIn("**logical grouping, not a directory**", DOC_FLAT)
        for package in ("db", "http"):
            subpackages = [
                p.name
                for p in (ROOT / "odoo" / package).iterdir()
                if p.is_dir() and (p / "__init__.py").exists() and p.name != "tests"
            ]
            self.assertEqual(
                [],
                subpackages,
                f"odoo/{package}/ is no longer flat ({subpackages}); the map's "
                "'[brackets] are not directories' notation is now misleading",
            )


class TestHttpLifecycle(unittest.TestCase):
    """The lifecycle sketch must name functions that exist, where they live."""

    def test_retrying_lives_in_service_transaction(self) -> None:
        self.assertIn("`retrying()` lives in `odoo/service/transaction.py`", DOC_FLAT)
        self.assertNotIn("Model.retrying", DOC)
        src = (ROOT / "odoo" / "service" / "transaction.py").read_text(encoding="utf-8")
        self.assertRegex(
            src,
            re.compile(r"^def retrying\b", re.MULTILINE),
            msg="retrying() moved again",
        )

    def test_named_hooks_exist_on_ir_http(self) -> None:
        src = (ROOT / "odoo" / "addons" / "base" / "models" / "ir_http.py").read_text(
            encoding="utf-8"
        )
        for hook in ("_match", "_authenticate", "_pre_dispatch", "_post_dispatch"):
            self.assertIn(f"ir.http.{hook}", DOC, f"{hook} dropped from the sketch")
            self.assertRegex(
                src,
                re.compile(rf"^    def {hook}\b", re.MULTILINE),
                f"ir.http.{hook} no longer exists",
            )

    def test_dispatcher_subclasses(self) -> None:
        src = (ROOT / "odoo" / "http" / "dispatcher.py").read_text(encoding="utf-8")
        named = re.search(r"three subclasses \(`(\w+)`, `(\w+)`,\s*\n?`(\w+)`\)", DOC)
        self.assertIsNotNone(named, "the Dispatcher subclass list is no longer stated")
        on_disk = set(re.findall(r"^class (\w+)\(Dispatcher\):", src, re.MULTILINE))
        self.assertEqual(set(named.groups()), on_disk)

    def test_serve_entry_points_exist(self) -> None:
        src = (ROOT / "odoo" / "http" / "_serve.py").read_text(encoding="utf-8")
        for fn in ("_serve_static", "_serve_nodb", "_serve_db"):
            self.assertIn(fn, DOC)
            self.assertRegex(src, re.compile(rf"^    def {fn}\b", re.MULTILINE))

    def test_commit_is_inside_retrying(self) -> None:
        """Not a step after it.

        The first draft of the sketch ended "→ commit/rollback → response +
        session save", reading as if ``_serve_db`` committed after the retry
        loop returned. It does not: ``retrying()`` commits, and ``_serve_db``'s
        ``finally`` only closes the cursor.
        """
        self.assertIn("is the last thing `retrying()` does", DOC_FLAT)
        transaction = (ROOT / "odoo" / "service" / "transaction.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("env.cr.commit()", transaction)
        serve = (ROOT / "odoo" / "http" / "_serve.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "cr.commit()",
            serve,
            "_serve_db commits now; the lifecycle note says retrying() does",
        )

    def test_session_is_saved_in_post_dispatch(self) -> None:
        """And therefore *before* the commit, not after it."""
        self.assertIn("`Request._save_session()`", DOC_FLAT)
        dispatcher = (ROOT / "odoo" / "http" / "dispatcher.py").read_text(
            encoding="utf-8"
        )
        body = dispatcher.split("def post_dispatch", 1)[1].split("\n    def ", 1)[0]
        self.assertIn(
            "_save_session()",
            body,
            "the session is no longer saved from Dispatcher.post_dispatch",
        )

    def test_ro_rw_promotion_is_real(self) -> None:
        """The page warns about the double-run; the retry must still be there."""
        self.assertIn("the handler runs a second time", DOC_FLAT)
        src = (ROOT / "odoo" / "http" / "_serve.py").read_text(encoding="utf-8")
        self.assertIn("psycopg.errors.ReadOnlySqlTransaction", src)

    #: The three lifecycle claims are about *when*, and the assertions above are
    #: all text searches, which cannot see order: move the commit above the
    #: dispatcher call and every one of them still passes. Each therefore names
    #: the DB-backed test that observes it, and this suite checks those tests
    #: exist -- the boundary job is stdlib-only and cannot run them itself.
    BEHAVIOURAL_COVER = {
        "addons/test_http/tests/test_lifecycle_order.py": (
            "test_session_is_saved_before_the_commit",
            "test_commit_is_the_last_thing_on_the_serving_thread",
            "test_promotion_reruns_the_handler_and_still_saves_before_committing",
        ),
        "addons/test_http/tests/test_models.py": (
            "test_promotion_replay_does_not_inherit_the_aborted_env",
        ),
    }

    def test_ordering_claims_have_a_runtime_test(self) -> None:
        for rel, names in self.BEHAVIOURAL_COVER.items():
            path = ROOT / "odoo" / rel
            self.assertTrue(
                path.is_file(),
                f"{rel} is gone; the ordering claims are back to being grep-only",
            )
            src = path.read_text(encoding="utf-8")
            for name in names:
                self.assertRegex(
                    src,
                    rf"\n    def {name}\(",
                    f"{rel} no longer defines {name}",
                )

    def test_the_runtime_test_is_registered(self) -> None:
        """An unimported test module is a test that never runs."""
        init = ROOT / "odoo" / "addons" / "test_http" / "tests" / "__init__.py"
        self.assertIn("from . import test_lifecycle_order", init.read_text())

    def test_the_page_names_where_the_proof_is(self) -> None:
        self.assertIn("test_lifecycle_order.py", DOC_FLAT)


class TestSeams(unittest.TestCase):
    """Each documented decoupling seam must still be wired the documented way."""

    def test_flushing_savepoint_injection(self) -> None:
        self.assertIn("BaseCursor._flushing_savepoint_cls", DOC)
        cursor = (ROOT / "odoo" / "db" / "cursor.py").read_text(encoding="utf-8")
        self.assertIn("_flushing_savepoint_cls", cursor)
        savepoint = (ROOT / "odoo" / "orm" / "runtime" / "savepoint.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "BaseCursor._flushing_savepoint_cls = _OrmFlushingSavepoint", savepoint
        )

    def test_recordset_injection_seam(self) -> None:
        self.assertIn("set_base_model()", DOC)
        src = (ROOT / "odoo" / "orm" / "_recordset.py").read_text(encoding="utf-8")
        self.assertRegex(src, re.compile(r"^def set_base_model\b", re.MULTILINE))

    def test_backend_port(self) -> None:
        self.assertIn("`runtime/backend.py`'s\n`InMemoryBackend`", DOC)
        src = (ROOT / "odoo" / "orm" / "runtime" / "backend.py").read_text(
            encoding="utf-8"
        )
        self.assertRegex(src, re.compile(r"^class InMemoryBackend\b", re.MULTILINE))

    def test_env_core_facade(self) -> None:
        self.assertIn("`env._core` (`components/core.py`)", DOC_FLAT)
        core = (ROOT / "odoo" / "orm" / "components" / "core.py").read_text(
            encoding="utf-8"
        )
        self.assertRegex(core, re.compile(r"^class OrmCore\b", re.MULTILINE))
        env = (ROOT / "odoo" / "orm" / "runtime" / "environment.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def _core(self)", env)

    def test_the_raw_objects_really_are_private(self) -> None:
        """ "the raw objects stay private to Transaction" was false when written.

        ``OrmCore``'s slots were named ``cache``/``engine``, so ``env._core.cache``
        WAS ``transaction._cache_store`` -- the curated facade handed out the raw
        collaborator it claimed to be curating. The slots are ``_cache``/``_engine``
        now, with ``get_value``/``set_value`` on the facade, and the claim is true.
        Nothing on this page checked it, which is why the sentence outlived the
        thing it described; this asserts the property rather than the class name.
        """
        core = (ROOT / "odoo" / "orm" / "components" / "core.py").read_text(
            encoding="utf-8"
        )
        slots = re.search(r"__slots__ = \(([^)]*)\)", core)
        self.assertIsNotNone(slots, "OrmCore no longer declares __slots__")
        names = re.findall(r'"(\w+)"', slots.group(1))
        self.assertTrue(names, "OrmCore's __slots__ is empty")
        public = [n for n in names if not n.startswith("_")]
        self.assertEqual(
            public,
            [],
            f"OrmCore exposes its collaborator(s) {public} as public attributes, "
            f"so the page's 'raw objects stay private' claim is false again",
        )
        transaction = (ROOT / "odoo" / "orm" / "runtime" / "transaction.py").read_text(
            encoding="utf-8"
        )
        for named in ("_cache_store", "_compute_engine"):
            self.assertIn(
                f'"{named}"', transaction, f"{named} is not a Transaction slot"
            )
            self.assertIn(f"`{named}`", DOC, f"the page no longer names {named}")

    def test_transaction_storage_sniffing_is_gone(self) -> None:
        """ADR-0011's claim: production CRUD no longer reads transaction.storage.

        And, since the 2026-08-08 amendment, does not sniff via ``env.backend is
        None`` either -- which is what ADR-0011 actually left behind. The null
        check WAS the PostgreSQL implementation, so grepping only for
        ``transaction.storage`` reported the sniff gone while it had merely been
        renamed. Both spellings are checked now, across the mixins AND the two
        Layer-1 field modules that carried four of the fifteen sites.
        """
        self.assertIn(
            "Production CRUD sniffs the test backend neither via "
            "`transaction.storage` nor via a null check.",
            DOC_FLAT,
        )
        scopes = [
            ROOT / "odoo" / "orm" / "models" / "mixins",
            ROOT / "odoo" / "orm" / "fields",
        ]
        offenders = [
            (p.relative_to(ROOT), needle)
            for directory in scopes
            for p in directory.rglob("*.py")
            for needle in (
                "transaction.storage",
                "backend is None",
                "backend is not None",
            )
            if needle in p.read_text(encoding="utf-8")
        ]
        self.assertEqual([], offenders)

    def test_the_capability_figures_state_their_denominator(self) -> None:
        """Three numbers, three denominators — the page must give all three.

        The module view carried a bare "Three sites still branch". True, of the
        fifteen pinned dispatch sites; false of the obvious measurement, which
        is ``backend.supports_*`` in the ORM and answers six. Nothing read
        either, so the sentence was reproducible only by someone who already
        knew which of the two it meant. A count whose denominator is unstated is
        not a measurement.
        """
        backend = (ROOT / "odoo" / "orm" / "runtime" / "backend.py").read_text(
            encoding="utf-8"
        )
        protocol = backend.split("class ", 2)[1]
        declared = set(re.findall(r"^\s+(supports_\w+): bool$", protocol, re.MULTILINE))

        reads: set[tuple[str, str]] = set()
        for path in sorted((ROOT / "odoo" / "orm").rglob("*.py")):
            if "tests" in path.parts or path.name.startswith("test_"):
                continue
            rel = str(path.relative_to(ROOT / "odoo" / "orm"))
            reads.update(
                (rel, cap)
                for cap in re.findall(
                    r"backend\.(supports_\w+)", path.read_text("utf-8")
                )
            )

        self.assertIn(f"{len(declared)} declared", DOC_FLAT)
        self.assertIn(f"{len(reads)} read sites", DOC_FLAT)
        for cap in declared:
            self.assertIn(f"`{cap}`", DOC, f"{cap} is declared and undocumented")
        self.assertEqual(
            {cap for _, cap in reads},
            declared,
            "a capability is read that the Protocol does not declare, or vice versa",
        )

    def test_no_view_still_teaches_the_null_backend(self) -> None:
        """The sentinel must be gone from the prose too, not only the code.

        ``test_transaction_storage_sniffing_is_gone`` above reads the mixins and
        the field modules, and passed throughout — while ``runtime.md``'s
        Transaction sketch went on labelling the slot ``None = PostgreSQL`` for
        a day after ``PostgresBackend`` had a name. A gate that reads only the
        implementation cannot see a document teaching the retired shape, and a
        diagram is where a reader learns it.

        ``None`` is only forbidden as the *backend's* value: the word is
        ordinary English elsewhere on these pages.
        """
        for line in DOC.splitlines():
            if "backend" not in line.lower():
                continue
            self.assertNotRegex(
                line,
                r"None\s*=\s*Postgre|backend\s+is\s+None",
                "a view still describes env.backend as None for PostgreSQL",
            )
        # The positive half: the slot must be named after its implementor.
        self.assertIn("PostgresBackend", DOC)
        transaction = (ROOT / "odoo" / "orm" / "runtime" / "transaction.py").read_text(
            encoding="utf-8"
        )
        self.assertNotRegex(
            transaction,
            r"self\.backend\s*=\s*[^\n]*\belse\s+None",
            "backend is optional again; the views say it is not",
        )

    def test_paid_down_relocations(self) -> None:
        """The three 2026-06 fixes must have stayed fixed."""
        primitives = (ROOT / "odoo" / "orm" / "primitives.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("MODULE_UNINSTALL_FLAG", primitives)

        number_format = ROOT / "odoo" / "libs" / "locale" / "number_format.py"
        src = number_format.read_text(encoding="utf-8")
        self.assertIn("class LocaleConventions(Protocol):", src)
        for fn in ("format_number", "intersperse", "split", "parse_grouping"):
            self.assertIn(f"`{fn}`", DOC)
            self.assertRegex(src, re.compile(rf"^def {fn}\b", re.MULTILINE))

        # An *import*, not a mention: osutil's docstrings still name
        # ``odoo.release`` as the expected caller, which is the point of the
        # fix, so a substring check would fail on the very wording that proves
        # the claim.
        osutil = ROOT / "odoo" / "libs" / "filesystem" / "osutil.py"
        self.assertNotIn(
            "odoo.release",
            _imported_modules(osutil),
            "libs/filesystem/osutil.py imports odoo.release again",
        )

        for module in ("esbuild", "esm_bridges", "esm_graph", "esm_registry"):
            self.assertTrue(
                (ROOT / "odoo" / "tools" / "assets" / f"{module}.py").is_file()
            )
            self.assertFalse((ROOT / "odoo" / "libs" / f"{module}.py").is_file())
        # ``asset_log`` stays: logging helpers over a logger-name string, with
        # no framework knowledge in them. ``constants`` did NOT stay -- the
        # 2026-06 relocation left it in ``libs/`` as a "dependency-free helper"
        # because the import gate said so, and it held 24 asset paths (two into
        # optional business addons), the ORM prefetch limits and the cron NOTIFY
        # channels. Split to ``tools/assets/constants.py``, ``orm/primitives.py``
        # and ``tools/constants.py`` on 2026-08-09.
        self.assertTrue((ROOT / "odoo" / "libs" / "asset_log.py").is_file())
        self.assertFalse((ROOT / "odoo" / "libs" / "constants.py").is_file())
        for relocated in ("tools/assets/constants", "tools/constants"):
            self.assertTrue((ROOT / "odoo" / f"{relocated}.py").is_file())


class TestCronExceptionRationale(unittest.TestCase):
    """The pinned cron exception rests on four checkable facts."""

    JOB_ENTRY_POINTS = (
        ("ir_cron.py", "IrCron"),
        ("ir_job.py", "IrJob"),
    )

    def test_entry_points_are_staticmethods(self) -> None:
        self.assertIn("`@staticmethod` entry points", DOC_FLAT)
        for filename, _cls in self.JOB_ENTRY_POINTS:
            src = (ROOT / "odoo" / "addons" / "base" / "models" / filename).read_text(
                encoding="utf-8"
            )
            self.assertRegex(
                src,
                r"@staticmethod\n    def _process_jobs\(",
                f"{filename}: _process_jobs is no longer a @staticmethod",
            )

    def test_imports_are_deferred_to_call_time(self) -> None:
        self.assertIn("Both imports are deferred to call time", DOC_FLAT)
        for filename in ("_threaded.py", "_worker.py"):
            src = (ROOT / "odoo" / "service" / filename).read_text(encoding="utf-8")
            for line in src.splitlines():
                if "from odoo.addons.base.models.ir_" in line:
                    self.assertTrue(
                        line.startswith("        "),
                        f"{filename}: the cron import is no longer function-local, "
                        "which breaks the documented rationale for pinning it",
                    )

    def test_no_override_exists_in_this_repo(self) -> None:
        """The page claims no override exists; check the tree it can see."""
        self.assertIn("no override of either exists anywhere", DOC_FLAT)
        definitions = [
            p.relative_to(ROOT)
            for p in (ROOT / "odoo" / "addons").rglob("*.py")
            if re.search(
                r"^    def _process_jobs\(", p.read_text(encoding="utf-8"), re.MULTILINE
            )
        ]
        self.assertEqual(
            sorted(str(p) for p in definitions),
            [
                "odoo/addons/base/models/ir_cron.py",
                "odoo/addons/base/models/ir_job.py",
            ],
        )


class TestRuntimeSurfaceFigures(unittest.TestCase):
    """Surface figures must come from a live run, never from a sibling docstring.

    The page said ``orm/fields`` reaches **5** unsanctioned private ``Environment``
    members. It reaches 4; five is the size of the distinct private set across the
    whole ORM, because ``_field_depends_context`` is reached from both packages.
    The slip was authored in ``env_surface_check.py``'s own module docstring and
    copied here, so *both* prose copies agreed with each other and neither agreed
    with the checker -- which is the exact failure mode a doc gate exists to catch
    and could not, because nothing compared either sentence to a run.
    """

    @staticmethod
    def _env_by_package() -> dict[str, dict[str, set[str]]]:
        import env_surface_check

        buckets: dict[str, dict[str, set[str]]] = {}
        for reach in env_surface_check.check().reaches:
            bucket = buckets.setdefault(reach.layer, {"pub": set(), "prv": set()})
            bucket["prv" if reach.is_private else "pub"].add(reach.attr)
        for bucket in buckets.values():
            bucket["prv"] -= set(env_surface_check.SANCTIONED_PRIVATE)
        return buckets

    #: The inversion table's rows, in order, each with the live measurement
    #: that produces it. Parsed by position for the same reason the composition
    #: table is: a reordered row would otherwise compare the wrong pair.
    INVERSION_ROWS = (
        "`Registry` accesses",
        "`pool[<model>]` subscripts",
        "distinct `Registry` members",
        "unsanctioned `Environment` privates",
        "accesses to those privates",
    )

    @classmethod
    def _inversion_table(cls) -> dict[str, tuple[int, int]]:
        """``{row label: (layer 1, layer 2)}`` from ``module.md``.

        Bold marks the heavier side, so it is stripped before parsing: which
        side is emphasised is a claim in its own right and is asserted
        separately, against the measurement rather than against the markup.
        """
        rows: dict[str, tuple[int, int]] = {}
        for line in DOC.splitlines():
            for label in cls.INVERSION_ROWS:
                if line.startswith(f"| {label} |"):
                    cells = [c.strip().strip("*") for c in line.split("|")[2:4]]
                    rows[label] = (int(cells[0]), int(cells[1]))
        return rows

    def _pool_measurements(self) -> dict[str, tuple[int, int]]:
        import pool_surface_check

        sites: dict[str, int] = {}
        members: dict[str, set[str]] = {}
        subscripts: dict[str, int] = {}
        for reach in pool_surface_check.check().reaches:
            sites[reach.layer] = sites.get(reach.layer, 0) + 1
            subscripts[reach.layer] = subscripts.get(reach.layer, 0) + reach.subscript
            # ``pool[...]`` is recorded as ``__getitem__``: the Mapping protocol
            # Registry implements, not a member of its surface. The checker's
            # own report excludes it from the member list and counts it as a
            # subscript, so the table must exclude it too.
            if not reach.attr.startswith("__"):
                members.setdefault(reach.layer, set()).add(reach.attr)
        return {
            "`Registry` accesses": (sites["Layer 1"], sites["Layer 2"]),
            "`pool[<model>]` subscripts": (
                subscripts.get("Layer 1", 0),
                subscripts.get("Layer 2", 0),
            ),
            "distinct `Registry` members": (
                len(members["Layer 1"]),
                len(members["Layer 2"]),
            ),
        }

    def _env_measurements(self) -> dict[str, tuple[int, int]]:
        """Unsanctioned private members, and the accesses to them.

        Two different numbers, and the reason both are stated: the page once
        quoted ``KNOWN_VIOLATIONS``' length (6 and 2) as the access count, but
        one entry covers all four ``base.py`` reaches of ``_field_cache_memo``.
        Sites are something only a run knows.
        """
        import env_surface_check

        sanctioned = set(env_surface_check.SANCTIONED_PRIVATE)
        members: dict[str, set[str]] = {}
        accesses: dict[str, int] = {}
        for reach in env_surface_check.check().reaches:
            if reach.is_private and reach.attr not in sanctioned:
                members.setdefault(reach.layer, set()).add(reach.attr)
                accesses[reach.layer] = accesses.get(reach.layer, 0) + 1
        return {
            "unsanctioned `Environment` privates": (
                len(members["Layer 1"]),
                len(members["Layer 2"]),
            ),
            "accesses to those privates": (
                accesses["Layer 1"],
                accesses["Layer 2"],
            ),
        }

    def test_the_inversion_table_lists_every_row_this_suite_measures(self) -> None:
        rows = self._inversion_table()
        self.assertEqual(
            sorted(self.INVERSION_ROWS),
            sorted(rows),
            "the runtime-channel table in module.md lost or renamed a row",
        )

    def test_every_inversion_row_re_derives(self) -> None:
        rows = self._inversion_table()
        self.assertTrue(
            rows,
            "no inversion rows parsed out of the document — the runtime-channel "
            "table is gone, so this test would compare nothing",
        )
        measured = self._pool_measurements() | self._env_measurements()
        for label in self.INVERSION_ROWS:
            with self.subTest(row=label):
                self.assertEqual(measured[label], rows[label], f"{label} is stale")

    def test_the_bold_side_is_the_heavier_one(self) -> None:
        """The emphasis is the argument; it must not survive the numbers moving.

        The paragraph's whole claim is that Layer 1 — the layer declared
        furthest below the runtime — is the heavier consumer on the channels
        that matter. Bold marks which side that is, so a row whose numbers
        invert while the markup stays put would state the opposite of what it
        measures.
        """
        measured = self._pool_measurements() | self._env_measurements()
        self.assertTrue(self._inversion_table(), "the inversion table is gone")
        for label in self.INVERSION_ROWS:
            with self.subTest(row=label):
                line = next(
                    ln for ln in DOC.splitlines() if ln.startswith(f"| {label} |")
                )
                cells = [c.strip() for c in line.split("|")[2:4]]
                layer1, layer2 = measured[label]
                heavier = 0 if layer1 > layer2 else 1
                self.assertTrue(
                    cells[heavier].startswith("**"),
                    f"{label}: the heavier side ({layer1} vs {layer2}) is not "
                    f"the emphasised one",
                )
                self.assertFalse(cells[1 - heavier].startswith("**"))

    def test_the_conclusion_survives_its_own_numbers(self) -> None:
        """Layer 1 must still be heavier on volume, Layer 2 wider on distinct.

        Guarding the *conclusion* separately from the digits, because both
        sides of a comparison can be re-measured correctly while the sentence
        around them is left claiming the opposite.
        """
        measured = self._pool_measurements() | self._env_measurements()
        self.assertGreater(*measured["`Registry` accesses"])
        self.assertGreater(*measured["unsanctioned `Environment` privates"])
        layer1, layer2 = measured["distinct `Registry` members"]
        self.assertGreater(
            layer2, layer1, "Layer 2 is no longer the wider consumer by member"
        )
        self.assertIn(
            "The inversion is one of volume, not of kind: Layer 2 reaches more "
            "*distinct* members",
            DOC_FLAT,
        )

    def test_the_union_is_named_as_a_union(self) -> None:
        """The page must state where the discredited 5 came from, not just drop it."""
        import env_surface_check

        union = {k.attr for k in env_surface_check.KNOWN_VIOLATIONS}
        self.assertEqual(len(union), 5, "the union figure the page explains is 5")
        self.assertIn("distinct private set across the whole ORM", DOC_FLAT)
        shared = sorted(
            attr
            for attr in union
            if len(
                {
                    "fields" if "/fields/" in k.path else "models"
                    for k in env_surface_check.KNOWN_VIOLATIONS
                    if k.attr == attr
                }
            )
            > 1
        )
        self.assertEqual(shared, ["_field_depends_context"])
        self.assertIn("`_field_depends_context` is reached from", DOC_FLAT)

    def test_layer2_private_reaches_are_named(self) -> None:
        """The page names Layer 2's own privates; the gate must find those."""
        import pool_surface_check

        privates = {
            reach.attr
            for reach in pool_surface_check.check().reaches
            if reach.layer == "Layer 2" and reach.is_private
        }
        self.assertTrue(privates, "Layer 2 has no private reach left")
        for attr in privates:
            self.assertIn(f"`{attr}`", DOC)


class TestGateInventoryIsWiredShut(unittest.TestCase):
    """Every checker the page lists must be a blocking step, and vice versa.

    ``pool_surface_check.py`` shipped as a standalone gate, was added to the table
    and to the workflow, and the page still carried a blockquote saying it was
    "not yet wired". The count sentence and the annotate condition drifted the
    same way: the sentence said *twelve* while the table had thirteen rows, and
    ``Annotate PR on failure`` listed twelve of thirteen step ids, so the one gate
    nobody had checked was also the one whose failure would post no annotation.
    """

    WORKFLOW = ROOT / ".github" / "workflows" / "architecture.yml"

    @classmethod
    def setUpClass(cls) -> None:
        cls.yaml = cls.WORKFLOW.read_text(encoding="utf-8")

    def _table_gates(self) -> list[str]:
        section = DOC.split("## Quality gates beyond the boundaries", 1)[1]
        return re.findall(r"^\| `([\w.]+\.py)` \|", section, re.MULTILINE)

    def _workflow_gates(self) -> list[str]:
        # DISTINCT checkers, not invocations. Eleven of them are run twice (once
        # to report, once for the JSON the summary step reads), so counting raw
        # matches said 35 where the workflow runs 24 gates.
        found = re.findall(r"python tooling/architecture/([\w.]+\.py)", self.yaml)
        return sorted(set(found))

    def test_table_matches_the_workflow(self) -> None:
        self.assertEqual(set(self._table_gates()), set(self._workflow_gates()))

    def test_the_reproduce_loop_is_exactly_the_contract_gates(self) -> None:
        """The ``for gate in …`` loop must be the contract gates, by membership.

        The count was derived and the membership was not, so the loop held the
        right *number* of the wrong names: it listed ``js_forced_render`` (a
        count ratchet, already driven by the loop below it, so it ran twice) and
        omitted ``js_deployment_layers`` entirely, which therefore appeared in no
        reproduce loop on the page. Twenty-three names, twenty-three contract
        gates, one of each swapped -- the shape ``test_the_cli_split_adds_up``
        cannot see, because both lists are the right length.

        This is the rule the page states two sections down, applied to the page:
        an enumerated list is a gate only when something derives the enumeration.
        """
        ratchets = set(
            re.findall(r"python tooling/architecture/([\w.]+\.py) --count", self.yaml)
        )
        contract = {
            gate.removesuffix(".py") for gate in set(self._workflow_gates()) - ratchets
        }
        loop = re.search(r"for gate in (.*?); do", DOC, re.DOTALL)
        self.assertIsNotNone(loop, "the reproduce loop is no longer on the page")
        listed = set(loop.group(1).replace("\\", "").split())
        self.assertEqual(
            listed,
            contract,
            "the reproduce loop and the workflow's contract gates disagree — "
            f"missing from the loop: {sorted(contract - listed)}; "
            f"in the loop but not a contract gate: {sorted(listed - contract)}",
        )

        # The ratchet loop is derived the same way, from the same yaml.
        ratchet_block = DOC.split("while read -r gate floor; do", 1)[1].split(
            "EOF\n```", 1
        )[0]
        piped = set(re.findall(r"^(\w+)\s+\w+$", ratchet_block, re.MULTILINE))
        self.assertEqual(piped, {r.removesuffix(".py") for r in ratchets})

    def test_stated_count_matches_both(self) -> None:
        words = NUMBER_WORD_BY_VALUE
        count = len(self._workflow_gates())
        self.assertIn(
            f"runs **{words[count]}** blocking checkers", DOC_FLAT, f"{count} gates run"
        )

    def _gates_without_a_check_flag(self) -> list[str]:
        """Gates whose argparse declares no ``--check``.

        By ``add_argument`` call, never by grepping the file or its ``--help``:
        four of these discuss ``--check`` in prose while rejecting it, so both
        cheaper reads answer "every gate has one". That is how the page came to
        say a ``--check`` loop "fails on three of them" when it fails on four.
        """
        out = []
        for gate in self._workflow_gates():
            source = ROOT / "tooling" / "architecture" / gate
            self.assertTrue(
                source.is_file(),
                f"architecture.yml runs {gate} as a blocking step and no such "
                f"file exists — the boundary job cannot pass",
            )
            tree = ast.parse(source.read_text(encoding="utf-8"))
            declared = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "add_argument"
                and any(
                    isinstance(a, ast.Constant) and a.value == "--check" for a in n.args
                )
                for n in ast.walk(tree)
            )
            if not declared:
                out.append(gate)
        return out

    def test_the_cli_split_adds_up_to_the_total(self) -> None:
        """Contract gates + count ratchets must equal the stated total.

        The page carried "Twenty are contract gates" directly above a loop of
        twenty-one names, beside "twenty-six" twice: 20 + 5 = 25, and nothing
        added them up. Each number was individually plausible, which is exactly
        the shape prose arithmetic fails in.
        """
        words = NUMBER_WORD_BY_VALUE
        total = len(self._workflow_gates())
        # A ratchet is a gate CI drives through tooling/ratchet, whether or not
        # it also implements --check: js_private_access has both.
        ratchets = set(
            re.findall(r"python tooling/architecture/([\w.]+\.py) --count", self.yaml)
        )
        contract = total - len(ratchets)
        self.assertEqual(
            contract + len(ratchets), total, "the two groups must partition the gates"
        )
        self.assertIn(
            f"**{words[contract].capitalize()} are contract gates.**", DOC_FLAT
        )
        self.assertIn(
            f"**{words[len(ratchets)].capitalize()} are count ratchets.**", DOC_FLAT
        )
        self.assertIn(
            f"a loop that assumes they do fails on "
            f"{words[len(self._gates_without_a_check_flag())]} of them",
            DOC_FLAT,
        )
        # The claim is only worth making if the arithmetic is stated as such.
        self.assertIn(
            f"{words[contract].capitalize()} plus {words[len(ratchets)]} is "
            f"{words[total]}",
            DOC_FLAT,
        )

    def test_the_gates_named_as_check_less_are_exactly_those(self) -> None:
        """The four named as implementing no ``--check`` must be the four."""
        named = set(self._gates_without_a_check_flag())
        for gate in named:
            self.assertIn(
                f"`{gate.removesuffix('.py')}`",
                DOC,
                f"{gate} implements no --check and the page does not say so",
            )
        # ...and nothing else may be described that way.
        sentence = DOC_FLAT.split("are count ratchets", 1)[1].split(
            "implement no `--check` at all", 1
        )[0]
        claimed = {f"{m}.py" for m in re.findall(r"`(\w+)`", sentence)}
        self.assertEqual(claimed, named)

    def test_every_gate_step_is_blocking(self) -> None:
        """A step that does not re-raise its exit code is a gate that cannot fail."""
        # Two idioms re-raise a gate's status: the original
        # `exit "${GATE_EXIT}"` and the `exit $rc` used by the steps that pipe a
        # count into tooling/ratchet. Both are blocking; counting only the first
        # read eleven live gates as unwired.
        #
        # Compared against the number of gate-running STEPS, not the number of
        # distinct gate files. One checker may legitimately run in two steps at
        # different scopes -- `js_public_surface` runs once for web and once for
        # mail -- and each of those steps needs its own re-raise. Counting unique
        # files made the second such step read as an unwired gate.
        reraised = self.yaml.count('exit "${GATE_EXIT}"') + self.yaml.count("exit $rc")
        steps = len(re.findall(r"^\s+id: \w+$", self.yaml, re.MULTILINE))
        self.assertEqual(reraised, steps)

    def test_annotate_condition_covers_every_step(self) -> None:
        ids = set(re.findall(r"^\s+id: (\w+)$", self.yaml, re.MULTILINE))
        condition = self.yaml.split("Annotate PR on failure", 1)[1].split("uses:", 1)[0]
        checked = set(re.findall(r"steps\.(\w+)\.outputs", condition))
        self.assertEqual(
            ids - checked,
            set(),
            "a gate step whose failure posts no PR annotation",
        )

    def test_no_gate_is_described_as_unwired(self) -> None:
        self.assertNotIn("Not yet wired", DOC)

    def test_the_outside_checker_is_counted_from_the_inside_ones(self) -> None:
        """``cross_repo_coherence.py`` is "an Nth checker" — N must track the table.

        Ordinals, so this one keeps its own map: "thirtieth" is not derivable
        from ``NUMBER_WORD_BY_VALUE``'s "thirty" by any rule worth writing.
        """
        ordinals = {
            12: "twelfth",
            13: "thirteenth",
            14: "fourteenth",
            15: "fifteenth",
            23: "twenty-third",
            24: "twenty-fourth",
            25: "twenty-fifth",
            26: "twenty-sixth",
            27: "twenty-seventh",
            28: "twenty-eighth",
            29: "twenty-ninth",
            30: "thirtieth",
            31: "thirty-first",
            32: "thirty-second",
            33: "thirty-third",
        }
        expected = ordinals[len(self._workflow_gates()) + 1]
        self.assertIn(f"is a {expected} checker and the only one outside CI", DOC_FLAT)


class TestRiskRegisterFigures(unittest.TestCase):
    """The risk register's numbers must come from a live run, like every other.

    ``risks.md`` arrived with four measured figures and a checker count, none of
    which any assertion read. Mutating R2's to ``Layer 2's 99`` and ``777
    Registry sites`` left the whole suite green -- the page was inside
    ``DOC_PATHS`` and therefore *looked* gated, while the only thing pinned
    about it was that its file existed.

    That is the failure this document set is built against, stated on the front
    door as *"if you add a number to this page, add the assertion with it"*, and
    it is worse in a risk register than anywhere else: an entry whose severity
    rests on a figure that has silently drifted argues for the wrong priority.
    The figures were correct when checked; nothing was keeping them so.
    """

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
        """R2's claim is a *comparison*; both sides of it must be live.

        The entry's whole argument is that Layer 1 is the heavier consumer on
        both channels, so a stale figure on either side could invert the
        conclusion while still reading as a measurement.
        """
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
        """Guard the conclusion, not only the digits.

        Both figures could be re-measured correctly by a future editor and the
        sentence around them left saying the opposite of what they show.
        """
        privates = self._env_unsanctioned_private_members()
        sites = self._registry_sites()
        self.assertGreater(privates["Layer 1"], privates["Layer 2"])
        self.assertGreater(sites["Layer 1"], sites["Layer 2"])
        self.assertIn("Layer 1 is the heavier consumer on both channels", DOC_FLAT)

    def test_the_digit_form_of_the_checker_count_tracks_the_workflow(self) -> None:
        """``gates.md`` spells the count as a word; the register uses digits.

        ``test_stated_count_matches_both`` pins *"runs **twenty-four** blocking
        checkers"*. Nothing read the three bare ``24``s in the register, so
        adding a gate would fail the word form and leave the digits wrong.
        Matched by shape rather than by whole sentence so a rewording of the
        surrounding prose does not silently drop the check.
        """
        expected = len(
            sorted(
                set(
                    re.findall(
                        r"python tooling/architecture/([\w.]+\.py)",
                        (ROOT / ".github" / "workflows" / "architecture.yml").read_text(
                            encoding="utf-8"
                        ),
                    )
                )
            )
        )
        cited = [
            int(n)
            for n in re.findall(
                r"(?:all|The) (\d+) (?:are structural|boundary checkers|and)",
                DOC_FLAT,
            )
        ]
        self.assertTrue(cited, "the register cites no checker count; regex rotted")
        self.assertEqual(
            set(cited),
            {expected},
            f"the register states a checker count the workflow does not run "
            f"(cited {sorted(set(cited))}, workflow runs {expected})",
        )

    def test_the_public_surface_pin_size_is_measured(self) -> None:
        """R6's severity is "how much is recorded"; that is a countable file."""
        pin = ROOT / "tooling" / "architecture" / "public_surface_web.txt"
        specifiers = [
            line
            for line in pin.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertIn(
            f"{len(specifiers)} specifiers",
            DOC_FLAT,
            f"the register's pin size disagrees with {pin.name} "
            f"({len(specifiers)} specifiers on disk)",
        )


class TestCitationsResolve(unittest.TestCase):
    """The citation forms ``test_named_source_paths_exist`` cannot see.

    That test only matches paths carrying a known top-level directory, so every
    bare ``<name>.py`` on the page went unchecked — which is how the page came to
    name ``test_pool_surface.py`` for a while after the file had been renamed.
    Matching *all* bare names is wrong: the page deliberately names ``sql_db.py``,
    ``http.py``, ``models.py``, ``api.py`` and ``fields.py`` as monoliths that no
    longer exist. So the rule is scoped to the one namespace where a bare name is
    always a live artefact — the checkers in ``tooling/architecture/``.
    """

    TOOLING = ROOT / "tooling" / "architecture"

    def test_bare_checker_names_exist(self) -> None:
        checkers = {p.name for p in self.TOOLING.glob("*.py")}
        named = set(re.findall(r"`(\w+_check(?:er)?\.py|\w+_coherence\.py)`", DOC))
        self.assertTrue(named, "the page names no checkers; the regex has rotted")
        missing = {n for n in named if n not in checkers}
        self.assertEqual(
            missing,
            set(),
            f"ARCHITECTURE.md names checker(s) that are not in "
            f"tooling/architecture/: {sorted(missing)}",
        )

    def test_line_number_citations_resolve(self) -> None:
        """``base.py:302`` outlived two rewrites of the file it pointed into.

        A ``file.py:N`` citation is checked three ways: the file exists, it has
        an Nth line, and — since a line number alone would still drift silently
        within a file — the sentence's claim about that line holds.
        """
        pattern = r"`([\w/]+\.py):(\d+)`"
        # The document is allowed to carry none: a pinned line number in a file
        # that keeps being refactored is the drift this test exists to catch,
        # so removing the last citation is a fix and must not read as a broken
        # regex. Proving the pattern still matches its own subject keeps the
        # vacuity guard the assertion below used to provide.
        self.assertTrue(
            re.findall(pattern, "see `orm/models/base.py:302` for the hook"),
            "the citation regex no longer matches a citation; it has rotted",
        )
        for name, lineno in re.findall(pattern, DOC):
            # Package-relative to ``odoo/``, the base the page uses throughout.
            # A bare ``base.py`` would be ambiguous -- ``orm/models/base.py`` and
            # ``orm/fields/base.py`` both exist -- so a citation must carry
            # enough path to name exactly one file.
            target = ROOT / "odoo" / name
            self.assertTrue(
                target.is_file(),
                f"`{name}:{lineno}` does not resolve under odoo/; a line "
                f"citation must carry enough path to be unambiguous",
            )
            lines = target.read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(
                len(lines),
                int(lineno),
                f"`{name}:{lineno}` is past the end of a {len(lines)}-line file",
            )
            sentence = DOC_FLAT.split(f"`{name}:{lineno}`", 1)[1]
            called = re.match(r" calls `([\w.]+)\(", sentence)
            if called:
                self.assertIn(called.group(1), lines[int(lineno) - 1])


class TestHttpCallGraphIsRecoverable(unittest.TestCase):
    """The page defers to a canonical call graph; it must still be somewhere.

    It pointed at ``odoo/http/__init__.py``'s module docstring, which
    ``4ffeacacd8c`` deleted along with every other docstring under ``odoo/``. The
    page went on calling itself the abridged version of a document that no longer
    existed, and no gate noticed: ``test_named_source_paths_exist`` proves the
    *file* exists, never its contents.
    """

    README = ROOT / "odoo" / "http" / "README.md"

    def test_the_pointer_resolves(self) -> None:
        self.assertIn("`odoo/http/README.md`", DOC)
        self.assertTrue(self.README.is_file())
        # The page may (and does) explain where the graph used to live; what it
        # must not do is still *point* there.
        self.assertNotIn("call graph is the module docstring", DOC_FLAT)

    def test_the_graph_is_actually_in_it(self) -> None:
        text = self.README.read_text(encoding="utf-8")
        for stage in (
            "Application.__call__",
            "Request._serve_static",
            "Request._serve_nodb",
            "Request._serve_db",
            "transaction.retrying(Request._serve_ir_http)",
            "transaction.retrying(Request._serve_ir_http_fallback)",
            "env['ir.http']._authenticate",
            "env['ir.http']._post_dispatch",
        ):
            self.assertIn(stage, text, f"the recovered call graph lost {stage}")

    def test_every_named_ir_http_hook_exists(self) -> None:
        ir_http = (
            ROOT / "odoo" / "addons" / "base" / "models" / "ir_http.py"
        ).read_text(encoding="utf-8")
        hooks = set(re.findall(r"env\['ir\.http'\]\.(\w+)", self.README.read_text()))
        self.assertTrue(hooks)
        for hook in hooks:
            self.assertRegex(ir_http, rf"\n    def {hook}\(")

    def test_every_named_request_method_exists(self) -> None:
        serve = (ROOT / "odoo" / "http" / "_serve.py").read_text(encoding="utf-8")
        methods = set(re.findall(r"Request\.(_serve_\w+)", self.README.read_text()))
        self.assertTrue(methods)
        for method in methods:
            self.assertRegex(serve, rf"\n    def {method}\(")


class TestPinnedCyclesAndRemovals(unittest.TestCase):
    """Two more prose claims that no gate read.

    Both are of the form the page's own thesis is about: a *number stated in
    prose that the code also states*, sitting next to gates that never compared
    them. ``py_cycle_check``'s three pinned cycles and the ``_monkeypatches``
    removal count were each measured once, written down, and left.
    """

    def test_pinned_cycles_are_the_ones_named(self) -> None:
        """The page lists each pinned cycle in full; compare member by member.

        It used to state a count and a package list, which is the weaker of the
        two available claims: a cycle can grow a member, or swap one, without
        moving either. Listing them means the page names the same edges the
        gate tolerates, and this compares the two sets directly.

        Derived from the run, never restated — the set was hardcoded to three
        once, so restoring ``odoo/tests/`` to the graph (the shipped test
        FRAMEWORK, dropped wholesale by a directory-name filter) turned a
        correct widening of the gate's coverage into a red build.
        """
        import py_cycle_check

        report = py_cycle_check.check()
        known = getattr(report, "known", None) or report.cycles
        measured = {" <-> ".join(cycle) for cycle in known}

        self.assertIn("Four are pinned, all the benign", DOC)
        block = DOC.split("Four are pinned, all the benign", 1)[1]
        block = block.split("```", 2)[1]
        listed = {
            " <-> ".join(part.strip() for part in line.split("<->"))
            for line in block.strip().splitlines()
            if line.strip()
        }
        self.assertEqual(
            measured,
            listed,
            "the pinned cycles in module.md and py_cycle_check disagree",
        )
        count = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}[len(measured)]
        self.assertIn(f"{count} are pinned, all the benign", DOC_FLAT)

    def test_the_orm_really_has_no_cycle(self) -> None:
        """ "The ORM has none" is the load-bearing half of that sentence."""
        import py_cycle_check

        report = py_cycle_check.check()
        orm = [c for c in report.cycles if any(m.startswith("odoo.orm") for m in c)]
        self.assertEqual(orm, [], "the ORM has a cycle; the page says it has none")
        self.assertIn("**The ORM has none.**", DOC_FLAT)

    def test_removed_module_count_and_names(self) -> None:
        """The page quotes six; the README's table has eight rows.

        Two of the eight retire a *patch* from a file that still exists
        (``werkzeug.py``, ``email.py``), which is exactly why the count and the
        row total differ — and why the page now names the six instead of only
        counting them.
        """
        readme = ROOT / "odoo" / "_monkeypatches" / "README.md"
        section = readme.read_text(encoding="utf-8").split("## Recently Removed", 1)[1]
        section = section.split("\n## ", 1)[0]
        rows = re.findall(r"^\| `([\w.]+\.py)`", section, re.MULTILINE)
        gone = sorted(
            name
            for name in rows
            if not (ROOT / "odoo" / "_monkeypatches" / name).exists()
        )
        self.assertEqual(len(rows), 8)
        self.assertEqual(len(gone), 6)
        for name in gone:
            self.assertIn(f"`{name.removesuffix('.py')}`", DOC)
        self.assertIn("names eight patches, six of which are", DOC_FLAT)

    def test_the_backtick_note_is_not_reinstated(self) -> None:
        """The removed names are backticked in the README; saying otherwise is false."""
        readme = (ROOT / "odoo" / "_monkeypatches" / "README.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("| `urllib3.py` |", readme)
        # The page may explain that the old claim was wrong; what it must not do
        # is assert it again.
        self.assertNotIn("Those names are quoted rather than backticked", DOC_FLAT)


class TestPatchModuleConvention(unittest.TestCase):
    """``each submodule exposes patch_module()`` was too broad by one file.

    ``_excel_utils.py`` exposes no ``patch_module``, and correctly: ``patch_init``
    skips ``_``-prefixed submodules, and the README files it as a ``UTIL``. The
    claim is true of the modules the hook actually registers, so that is what the
    page now says.
    """

    PKG = ROOT / "odoo" / "_monkeypatches"

    def test_every_registered_patch_exposes_the_hook(self) -> None:
        missing = [
            path.name
            for path in sorted(self.PKG.glob("*.py"))
            if not path.name.startswith("_")
            and "def patch_module(" not in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(missing, [])

    def test_the_underscore_exemption_is_real_and_stated(self) -> None:
        init = (self.PKG / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('if submodule.name.startswith("_"):', init)
        exempt = [
            path.name
            for path in sorted(self.PKG.glob("_*.py"))
            if path.name != "__init__.py"
            and "def patch_module(" not in path.read_text(encoding="utf-8")
        ]
        self.assertTrue(exempt, "no underscore helper left; simplify the page")
        # The claim sits inside the map's fenced block, so a ``│`` gutter glyph
        # survives whitespace-flattening mid-sentence; assert either side of it.
        self.assertIn("non-underscore submodule exposes `patch_module()`", DOC_FLAT)


class TestEdgeCountConventions(unittest.TestCase):
    """Two adjacent measurements counted by two different conventions.

    ``db``'s 6-against-1 is per imported *symbol*; ``http``'s 22-against-1 is per
    import *statement*. Both digits are right and neither is reproducible without
    knowing which — a reader who picks the other convention gets 5 and 39. The
    page now says which, and this recomputes both.

    **``TIERS`` below is deliberately the PRE-FIX bracket assignment**, with
    ``errors``/``dsn``/``utils`` in ``connectivity`` rather than in the
    ``[foundation]`` tier the subsystem map now documents. The figures on the
    page are the measurement that *justified* the two contracts, taken before
    those modules moved; reproducing them needs the map of that day. Do not
    "correct" this dict against the subsystem map — that measures a different
    claim, and all four numbers move. If the current-state figures are wanted,
    add them as their own rows with their own assertion rather than editing
    these.

    Two further traps this method already handles, both of which silently
    deflate a hand-rolled re-measurement: ``from . import x`` names its targets
    in ``node.names`` (skip it and ``db``'s back-edge vanishes), and imports
    under ``if TYPE_CHECKING:`` are excluded (count them and ``http``'s
    ``_protocols`` reads as five violations of a contract that is clean).
    """

    TIERS = {
        "db": {
            "connectivity": [
                "pool",
                "cursor",
                "ddl",
                "schema",
                "savepoint",
                "schema_cache",
                "bulk",
                "lifecycle",
                "errors",
                "dsn",
                "utils",
            ],
            "resilience": [
                "breaker",
                "lag",
                "budget",
                "leaks",
                "reaper",
                "metrics",
                "stats",
            ],
        },
        "http": {
            "serving": [
                "application",
                "dispatcher",
                "routing",
                "session",
                "request_class",
                "_serve",
                "_response",
                "wrappers",
                "stream",
                "_csrf",
                "controller",
                "core",
            ],
            "features": [
                "openapi",
                "_params",
                "geoip",
                "constants",
                "exceptions",
                "_protocols",
                "helpers",
            ],
        },
    }

    def _edges(self, package: str, per_symbol: bool) -> dict[tuple[str, str], int]:
        groups = self.TIERS[package]
        of = {mod: tier for tier, mods in groups.items() for mod in mods}
        counted: dict[tuple[str, str], int] = {}
        for path in sorted((ROOT / "odoo" / package).glob("*.py")):
            here = of.get(path.stem)
            if here is None:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            deferred: set[int] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(
                    node.test
                ):
                    deferred |= {id(inner) for inner in ast.walk(node)}
            for node in ast.walk(tree):
                if id(node) in deferred or not isinstance(node, ast.ImportFrom):
                    continue
                if node.level == 1 and node.module:
                    targets = [node.module.split(".")[0]]
                elif node.level == 1:
                    targets = [alias.name for alias in node.names]
                elif node.module and node.module.startswith(f"odoo.{package}."):
                    targets = [node.module.split(".")[2]]
                else:
                    continue
                for target in targets:
                    there = of.get(target)
                    if there is None or there == here:
                        continue
                    key = (here, there)
                    counted[key] = counted.get(key, 0) + (
                        len(node.names) if per_symbol else 1
                    )
        return counted

    def test_db_figures_are_per_symbol(self) -> None:
        edges = self._edges("db", per_symbol=True)
        self.assertEqual(edges[("connectivity", "resilience")], 6)
        self.assertEqual(edges[("resilience", "connectivity")], 1)
        self.assertIn("had 6 connectivity", DOC_FLAT)
        self.assertIn("counting imported *symbols*", DOC_FLAT)

    def test_http_figures_are_per_statement_and_the_symbol_count_is_given(self) -> None:
        per_statement = self._edges("http", per_symbol=False)
        per_symbol = self._edges("http", per_symbol=True)
        self.assertEqual(per_statement[("serving", "features")], 22)
        self.assertEqual(per_statement[("features", "serving")], 1)
        self.assertIn("22 serving", DOC_FLAT)
        self.assertIn(
            f"by symbol it is {per_symbol[('serving', 'features')]} against "
            f"{per_symbol[('features', 'serving')]}",
            DOC_FLAT,
        )


class TestFloorMethodologyExample(unittest.TestCase):
    """``gates.md``'s clean-worktree worked example, and the budget it quotes.

    The example is dated and one of its two numbers is a snapshot of somebody's
    dirty tree, which nothing can re-derive — that half is history and stays
    so. The other half is not: the row asserts, in the present tense and with a
    tick, that the clean-worktree figure **equals the committed floor**. That
    is a live claim about ``baselines/pyfunclen.json``, and it goes false the
    moment the floor moves for any ordinary reason.
    """

    def test_the_example_does_not_claim_to_be_the_current_floor(self) -> None:
        """It once did, with a tick, and was stale within the day.

        The example's worth is the *gap* and its cause, not the absolute: a
        floor that moves whenever anyone shortens a function cannot be restated
        on a page and stay true. So the page carries it as a dated measurement
        and points at the tool for today's value — and this asserts it has not
        drifted back into a present-tense claim, which is the shape that rots.
        """
        floor = json.loads(
            (ROOT / "tooling" / "ratchet" / "baselines" / "pyfunclen.json").read_text(
                encoding="utf-8"
            )
        )["count"]
        self.assertIn("`pyfunclen` that day", DOC, "the example lost its dating")
        self.assertIn(
            "this table is an illustration of the method and is not maintained",
            DOC_FLAT,
        )
        self.assertNotIn(
            "= the committed floor",
            DOC,
            "the worked example claims equality with the committed floor again; "
            f"it is {floor} today and the claim will rot the next time a "
            f"function is shortened",
        )

    def test_the_quoted_budget_is_the_gates_own(self) -> None:
        """80 is ``MAX_LINES``; the page must not carry a second copy of it."""
        src = (ROOT / "tooling" / "architecture" / "py_function_length.py").read_text(
            encoding="utf-8"
        )
        match = re.search(r"^MAX_LINES = (\d+)$", src, re.MULTILINE)
        self.assertIsNotNone(match, "py_function_length.MAX_LINES is gone")
        self.assertIn(f"*excess lines* over {match.group(1)}", DOC_FLAT)


class TestFilestoreLayout(unittest.TestCase):
    """The filestore table in ``data.md``, against ``libs/hashing.py``.

    Both digest lengths were unpinned, which is how one of them spent a while
    reading 99: a mutation-testing harness that rewrote the page on disk was
    killed mid-case and left its mutant behind, and nothing in the suite
    noticed a filestore path length that no algorithm produces. The lengths are
    a real interoperability claim — a deployment reading the other tag's paths
    has to know how long the digest is — so they are derived here from the
    constant the code indexes rather than restated beside it.
    """

    @staticmethod
    def _lengths_by_tag() -> dict[str, int]:
        src = (ROOT / "odoo" / "libs" / "hashing.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "CONTENT_DIGEST_LEN_BY_TAG"
                for t in node.targets
            ):
                return {
                    k.value: v.value
                    for k, v in zip(node.value.keys, node.value.values, strict=True)
                }
        raise AssertionError("CONTENT_DIGEST_LEN_BY_TAG is gone from libs/hashing.py")

    def test_each_tag_row_states_its_real_digest_length(self) -> None:
        lengths = self._lengths_by_tag()
        self.assertEqual({"s1", "b3"}, set(lengths), "the tag set changed")
        for tag, length in sorted(lengths.items()):
            with self.subTest(tag=tag):
                row = next(
                    (ln for ln in DOC.splitlines() if ln.startswith(f"| `{tag}` ")),
                    None,
                )
                self.assertIsNotNone(row, f"data.md has no row for tag {tag}")
                self.assertEqual(
                    str(length),
                    row.rsplit("|", 2)[1].strip(),
                    f"the {tag} row's digest length disagrees with "
                    f"CONTENT_DIGEST_LEN_BY_TAG",
                )

    def test_the_tag_is_still_chosen_by_an_optional_dependency(self) -> None:
        """The page's point is that the layout depends on blake3 being there."""
        src = (ROOT / "odoo" / "libs" / "hashing.py").read_text(encoding="utf-8")
        self.assertIn('ALGO_TAG = "b3" if HAS_BLAKE3 else "s1"', src)
        self.assertIn("depends on an optional dependency", DOC_FLAT)


class TestAddonSuiteFigures(unittest.TestCase):
    """Sizes ``gates.md`` quotes to argue what belongs in the integration lane.

    These are the numbers the lane's scope is argued from — "the largest thing
    outside the lane", "the next two worth taking" — so a stale one weakens a
    live decision rather than a historical note. Three of them were pinned by
    nothing and found by mutation: changing 613 to 999, 26,579 to 99,999 and
    9,203 to 9,999 left the whole suite green.

    Counted the way the page states its scope: the addon's ``tests/``
    directory, ``*.py``, ``def test*`` for methods. Stating the scope is what
    makes the figure a claim — the same lesson ``_metadata.py``'s call-site
    numbers taught, where a count sat between every candidate scope and could
    be neither confirmed nor refuted.
    """

    @staticmethod
    def _suite(module: str) -> tuple[int, int]:
        """``(test methods, lines)`` under ``<module>/tests/``."""
        for tree in ("addons", "odoo/addons"):
            base = ROOT / tree / module / "tests"
            if base.is_dir():
                break
        else:
            raise AssertionError(f"{module}/tests not found in either addon tree")
        methods = lines = 0
        for path in sorted(base.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            lines += len(text.splitlines())
            methods += sum(
                isinstance(n, ast.FunctionDef) and n.name.startswith("test")
                for n in ast.walk(ast.parse(text))
            )
        return methods, lines

    def test_the_test_orm_figure_is_measured(self) -> None:
        methods, _lines = self._suite("test_orm")
        self.assertIn(f"**{methods:,} test methods**", DOC_FLAT)

    def test_the_suites_still_outside_the_lane_are_measured(self) -> None:
        read_group, _ = self._suite("test_read_group")
        access_rights, _ = self._suite("test_access_rights")
        self.assertIn(f"`test_read_group` ({read_group} test", DOC_FLAT)
        self.assertIn(f"`test_access_rights` ({access_rights},", DOC_FLAT)

    def test_line_counts_are_not_quoted_for_these_suites(self) -> None:
        """The page says why it counts methods; hold it to that.

        A raw line count churns on every edit inside a suite without moving the
        argument the figure is making — `test_orm` lost 68 lines between two
        runs an hour apart while its method count did not move. This is the
        same call the composition table makes when it reports "root dominates
        its leaves" instead of two line counts.
        """
        self.assertIn("Method counts, not line counts.", DOC_FLAT)
        for module in ("test_orm", "test_read_group"):
            _methods, lines = self._suite(module)
            self.assertNotIn(f"{lines:,} lines", DOC_FLAT)

    def test_the_bundled_module_count_is_measured(self) -> None:
        """618, and it must mean manifests.

        ``ls -d addons/*/`` answers one more in any tree that has been run:
        ``__pycache__`` is a build artifact, not an addon. The page
        argues ``c901_addons``' existence from "where the N bundled modules and
        most business logic live", so N has to be modules.
        """
        modules = sum(
            1
            for path in (ROOT / "addons").iterdir()
            if (path / "__manifest__.py").is_file()
        )
        self.assertIn(f"the {modules} bundled modules", DOC_FLAT)


class TestTheEnforcedClaimIsBounded(unittest.TestCase):
    """The page says "enforced"; it must also say what that word does not cover.

    All thirteen boundary checkers are structural and DB-free -- import graphs,
    call graphs, reached-member sets, documents. None of them executes framework
    behaviour, so a change can be green across every gate and both DB-free tiers
    and still be wrong. That is not a thought experiment: renaming ``OrmCore``'s
    slots broke two DB-backed addon tests while everything measurable stayed
    green. The only lane that runs addon tests is ADR-0007's integration
    workflow, and a page claiming enforcement has to say so.
    """

    BOUNDARY = ROOT / ".github" / "workflows" / "architecture.yml"
    INTEGRATION = ROOT / ".github" / "workflows" / "integration_tests.yml"

    def test_the_boundary_job_really_has_no_database(self) -> None:
        """The claim "DB-free" must be true of the workflow, not just asserted."""
        yaml = self.BOUNDARY.read_text(encoding="utf-8")
        for marker in ("services:", "postgres", "POSTGRES_"):
            self.assertNotIn(
                marker,
                yaml,
                f"architecture.yml now provisions a database ({marker!r}); the "
                f"page's DB-free claim about the boundary gates is stale",
            )

    def test_the_integration_lane_is_the_one_with_a_database(self) -> None:
        yaml = self.INTEGRATION.read_text(encoding="utf-8")
        self.assertIn("postgres:18", yaml)
        self.assertIn("only lane that runs addon tests", DOC_FLAT)

    def test_every_installed_module_is_named_by_the_page(self) -> None:
        yaml = self.INTEGRATION.read_text(encoding="utf-8")
        installs = re.findall(r"^  (?:\w+_)?INSTALL: (.+)$", yaml, re.MULTILINE)
        self.assertTrue(installs, "the integration lane installs nothing")
        for spec in installs:
            for module in spec.split(","):
                self.assertIn(
                    f"`{module.strip()}`",
                    DOC,
                    f"the integration lane installs {module.strip()}, unmentioned",
                )

    def test_each_suite_gets_its_own_database(self) -> None:
        """Separate databases, because the suites interfere.

        ``test_http`` depends on ``mail``, whose ``res_partner_views.xml``
        inherits ``base.view_res_partner_filter`` anchored on
        ``<filter name="inactive">``. base's
        ``test_hard_reset_from_file_still_works`` overwrites that view with a
        minimal ``<search>``, and the write re-validates the children -- so
        ``-i base`` is 5/5 green and ``-i base,test_http`` raises
        ``ValidationError`` while running only that one test class. One database
        per suite is what keeps the next addon added here from tripping it.
        """
        yaml = self.INTEGRATION.read_text(encoding="utf-8")
        databases = re.findall(r"^\s+-d (\w+) \\$", yaml, re.MULTILINE)
        self.assertGreater(len(databases), 1, "only one suite runs")
        self.assertEqual(
            len(databases),
            len(set(databases)),
            f"two suites share a database, so they can interfere: {databases}",
        )
        installs = re.findall(r"^  (?:\w+_)?INSTALL: (.+)$", yaml, re.MULTILINE)
        self.assertEqual(
            len(databases),
            len(installs),
            "every suite must declare its own module set",
        )
        for spec in installs:
            self.assertNotIn(
                ",",
                spec,
                f"suites are combined into one database again ({spec!r}); the "
                f"base/test_http view-inheritance clash comes back",
            )

    def test_the_stated_suite_count_matches_the_lane(self) -> None:
        """The page must count the suites, not remember them.

        It said "three suites" and named three while the lane ran four: `mrp`
        was added and only ``test_every_installed_module_is_named_by_the_page``
        noticed, because that one reads the workflow. The count sentence did
        not, so it drifted the way every unread number here has -- and
        ``risks.md`` R4 drifted further, still saying *two* from the state
        before ``test_orm`` landed. Both now derive from the same list.
        """
        yaml = self.INTEGRATION.read_text(encoding="utf-8")
        words = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
        n = len(re.findall(r"^  (?:\w+_)?INSTALL: (.+)$", yaml, re.MULTILINE))
        self.assertIn(
            f"runs {words[n]} suites, **each against its own database**",
            DOC_FLAT,
            f"the lane runs {n} suites",
        )
        self.assertIn(f"it runs {words[n]} suites", DOC_FLAT, "risks.md R4 count")

    def test_the_ormcache_style_gap_is_named(self) -> None:
        """The concrete example is what stops this reading as boilerplate."""
        self.assertIn("OrmCore", DOC)
        self.assertIn('never as "the framework works"', DOC_FLAT)
        # The example must stay a real one: those slots must still be private.
        core = (ROOT / "odoo" / "orm" / "components" / "core.py").read_text(
            encoding="utf-8"
        )
        self.assertRegex(core, r"_cache\b")
        self.assertRegex(core, r"_engine\b")


class TestPermissionIsNotPractice(unittest.TestCase):
    """Where the page states a *permission*, it must not read as a measurement.

    The Layer-0 bullet paired ``odoo.tools``/``odoo_rust`` as helpers Layer 0
    "may still use", with an example covering only the first. The permission is
    real -- ``orm-layer0-is-foundational`` forbids higher ORM layers and nothing
    else -- but no Layer-0 module imports ``odoo_rust``, and a reader deciding
    where to put code would reasonably infer a dependency that does not exist.
    The page now says which half is exercised; this keeps that honest in both
    directions, so it also fails if Layer 0 *starts* importing ``odoo_rust``.
    """

    @property
    def LAYER0(self) -> tuple[str, ...]:
        """Layer 0's modules, from the contract rather than a second copy.

        Hardcoded here until ``orm/_protocols.py`` landed and this tuple did
        not grow with it — a module can only be missed by a completeness check
        that keeps its own list of what is complete.
        """
        contract = next(
            c for c in layer_check.CONTRACTS if c.name == "orm-layer0-is-foundational"
        )
        return tuple(dotted.rsplit(".", 1)[-1] for dotted in contract.source)

    def _layer0_importers(self) -> list[str]:
        return [
            name
            for name in self.LAYER0
            if "odoo_rust"
            in (ROOT / "odoo" / "orm" / f"{name}.py").read_text(encoding="utf-8")
        ]

    def test_layer0_does_not_import_odoo_rust(self) -> None:
        importers = self._layer0_importers()
        self.assertEqual(
            importers,
            [],
            f"Layer 0 now imports odoo_rust ({importers}); the page says it does "
            f"not -- update the bullet rather than deleting this test",
        )
        self.assertIn("no Layer-0 module imports `odoo_rust` at all", DOC_FLAT)

    def test_the_named_entry_points_are_where_odoo_rust_arrives(self) -> None:
        """The page names three; they must be exactly the ORM's importers."""
        orm = ROOT / "odoo" / "orm"
        actual = sorted(
            str(path.relative_to(orm))
            for path in orm.rglob("*.py")
            if "tests" not in path.parts
            and "odoo_rust" in path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            actual,
            ["helpers.py", "models/mixins/read.py", "runtime/environment.py"],
        )
        for name in actual:
            self.assertIn(f"`{name}`", DOC)

    def test_the_permission_is_really_granted(self) -> None:
        """``orm-layer0-is-foundational`` must forbid ORM layers and nothing else."""
        contract = next(
            c for c in layer_check.CONTRACTS if c.name == "orm-layer0-is-foundational"
        )
        # Not just ``odoo.orm.*``: the façades are re-export shims over exactly
        # those layers, so a rule that ignored them would be one import away
        # from useless. The page must name both halves or a reader will try it.
        facades = {"odoo.fields", "odoo.models", "odoo.api"}
        self.assertTrue(
            facades <= set(contract.forbidden),
            f"the façades are no longer blocked for Layer 0: {contract.forbidden}",
        )
        self.assertTrue(
            all(f.startswith("odoo.orm.") or f in facades for f in contract.forbidden),
            f"the contract forbids something that is neither the ORM nor a "
            f"façade, so the page's paraphrase is now wrong: {contract.forbidden}",
        )
        # Assert the façades by their FULL dotted name. ``removeprefix("odoo.")``
        # would reduce ``odoo.fields`` to ``fields``, which the page backticks in
        # a dozen unrelated places -- an assertion that passes whether or not the
        # façade half is stated, as a mutation of this very paragraph showed.
        # The Layer-0 ROW of the layer table, not a bullet: the per-layer
        # bullets became a table, and a split on prose that no longer exists
        # raises IndexError rather than failing with a diagnosis.
        rows = [ln for ln in DOC.splitlines() if ln.startswith("| **0** ")]
        self.assertEqual(
            1, len(rows), "the layer table has no single Layer-0 row to read"
        )
        bullet = rows[0]
        for dotted in contract.forbidden:
            wanted = dotted if dotted in facades else dotted.removeprefix("odoo.")
            self.assertIn(
                f"`{wanted}`",
                bullet,
                f"the Layer-0 bullet does not name {dotted}",
            )


class TestDeploymentLimits(unittest.TestCase):
    """The deployment view's knob table must come from ``config.py``.

    This table had no gate at all, and it went materially wrong in the way an
    operator would act on: it listed ``limit_memory_hard`` as "worker is killed"
    and sold the 512 MB between soft and hard as "the headroom a request has to
    complete". Nothing in ``odoo/service/`` reads ``limit_memory_hard``. The
    in-process ``RLIMIT_AS`` behind it was removed -- the allocator and gevent
    reserve multi-GB of never-resident virtual space, which that rlimit counts
    and RSS does not -- and ``config.py``'s own help has said
    "Deprecated/not enforced in-process" since. A deployment sized on the old
    paragraph has no hard ceiling but the OOM killer.

    Every other row was correct, which is the point: a table of plausible
    defaults is exactly where one retired row hides.
    """

    CONFIG = ROOT / "odoo" / "tools" / "config.py"
    SERVICE = ROOT / "odoo" / "service"

    @staticmethod
    def _literal(node: ast.AST) -> object:
        """``2048 * 1024 * 1024`` is a ``BinOp``, not a literal."""
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Mult, ast.Add, ast.Pow)
        ):
            left = TestDeploymentLimits._literal(node.left)
            right = TestDeploymentLimits._literal(node.right)
            if isinstance(left, int) and isinstance(right, int):
                if isinstance(node.op, ast.Mult):
                    return left * right
                return left + right if isinstance(node.op, ast.Add) else left**right
            return None
        try:
            return ast.literal_eval(node)
        except ValueError, SyntaxError:
            return None

    def _defaults(self) -> dict[str, object]:
        tree = ast.parse(self.CONFIG.read_text(encoding="utf-8"))
        found: dict[str, object] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kwargs = {k.arg: k.value for k in node.keywords if k.arg}
            dest = kwargs.get("dest")
            if isinstance(dest, ast.Constant) and "my_default" in kwargs:
                found[dest.value] = self._literal(kwargs["my_default"])
        return found

    def _table(self) -> dict[str, str]:
        # Bounded at the next heading: DOC is every view concatenated, so an
        # unbounded split runs on into scenarios.md's migration-stage table and
        # reads `pre` as a config option.
        section = DOC.split("## The limits that end a request or a worker", 1)[1]
        section = re.split(r"^## ", section, maxsplit=1, flags=re.MULTILINE)[0]
        rows = re.findall(r"^\| `(\w+)` \| `?([^|`]+?)`? \|", section, re.MULTILINE)
        return {name: value.strip() for name, value in rows}

    def test_the_soft_hard_gap_is_derived(self) -> None:
        """512 MB is ``hard - soft``, and the page's point rests on it.

        The paragraph argues that a deployment "sized on the 512 MB between the
        two" has no hard ceiling at all, so the figure is load-bearing for the
        warning rather than decorative — and it was the last number in the
        knob section that no assertion re-derived.
        """
        defaults = self._defaults()
        soft = defaults["limit_memory_soft"]
        hard = defaults["limit_memory_hard"]
        self.assertIsInstance(soft, int)
        self.assertIsInstance(hard, int)
        gap = (hard - soft) // 1024 // 1024
        self.assertIn(
            f"sized on the {gap} MB between the two",
            DOC_FLAT,
            f"the stated soft/hard gap disagrees with config.py ({gap} MB)",
        )

    def test_every_stated_default_matches_config(self) -> None:
        defaults = self._defaults()
        table = self._table()
        self.assertGreaterEqual(len(table), 8, "the knob table lost its rows")
        for knob, stated in table.items():
            self.assertIn(knob, defaults, f"{knob} is not a config option")
            actual = defaults[knob]
            if stated.endswith("MB"):  # written in MB, stored in bytes
                actual //= 1024 * 1024
                stated = stated.removesuffix(" MB")
            stated = stated.removesuffix(" s")  # seconds are written with a unit
            self.assertEqual(
                str(actual), stated, f"{knob}: page says {stated}, config says {actual}"
            )

    def test_only_the_soft_memory_limit_is_enforced(self) -> None:
        """The claim the old paragraph got wrong, stated as a check."""
        read_by = {
            option: sorted(
                p.name
                for p in self.SERVICE.rglob("*.py")
                if f'config["{option}"]' in p.read_text(encoding="utf-8")
            )
            for option in ("limit_memory_soft", "limit_memory_hard")
        }
        self.assertTrue(
            read_by["limit_memory_soft"], "nothing enforces the soft limit either"
        )
        self.assertEqual(
            [],
            read_by["limit_memory_hard"],
            "odoo/service/ enforces limit_memory_hard again; the deployment view "
            "says nothing does",
        )
        self.assertIn("enforced by nothing in-process", DOC_FLAT)
        self.assertIn("There is one memory limit, not a pair", DOC_FLAT)
        # config.py must keep saying so too, or the page is the only warning.
        self.assertIn(
            "not enforced in-process", self.CONFIG.read_text(encoding="utf-8")
        )


class TestQualityFigureArithmetic(unittest.TestCase):
    """``qualities.md`` states ratios beside their operands; they must agree.

    This page had no assertions at all, on the reasoning that a measurement
    cannot be re-derived from source. True of the measurements — and its
    *conclusions* are arithmetic over them, which is checkable and is the half
    that drifts: "costs **50×** more than loading one (35.85 s against 0.72 s)"
    is three numbers that must stay consistent through any re-measurement, and
    a re-measured pair with the old ratio left beside it is exactly the shape
    this document set keeps finding.

    So: nothing here judges whether a figure is *right*, only that the page
    agrees with itself and that every scenario still says when it was taken.
    """

    # Read through DOC, never off disk. Reading ``qualities.md`` directly is
    # what made all three of these survive an empty page -- they passed against
    # a document that says nothing, because they were not reading the document
    # under test. ``test_architecture_doc_is_not_vacuous`` caught it.

    def test_the_cold_over_warm_ratios_match_their_operands(self) -> None:
        """Every "N×" stated with its two seconds must be their quotient."""
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
        """The re-measured ratio row must divide its own columns."""
        # Scoped to the re-measurement table: Scenario 2 carries two tables with
        # the same row labels, and an unscoped scan pairs a row of one against
        # the ratio row of the other.
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
            # "0.746 / 0.765 s" — take the first, they are repeats of one run.
            return float(re.findall(r"[\d.]+", cell)[0])

        for column, (b, w, r) in enumerate(zip(build, warm, ratio, strict=True)):
            self.assertAlmostEqual(
                float(re.findall(r"\d+", r)[0]),
                seconds(b) / seconds(w),
                delta=1.5,
                msg=f"column {column}: {b} / {w} is not {r}",
            )

    def test_every_scenario_carries_a_date(self) -> None:
        """ "one that is not dated will be read as current forever" — its own rule."""
        self.assertIn(
            "A number added to this page must arrive with its command and its date",
            DOC_FLAT,
        )
        headings = re.findall(r"^## (Scenario \d[^\n]*)", DOC, re.MULTILINE)
        self.assertGreaterEqual(
            len(headings), 4, "qualities.md lost its scenarios, or they were renamed"
        )
        for heading in headings:
            body = DOC.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
            dated = re.search(r"20\d\d-\d\d-\d\d", body) or "| Measured |" in DOC
            self.assertTrue(dated, f"{heading} carries no date, here or in the header")


class TestLifecycleSketches(unittest.TestCase):
    """The ``Lifecycles`` sketches must name callables that exist, in call order.

    The page carried one lifecycle (HTTP) and pinned it hard, because its three
    ordering claims had already drifted once. The boot, registry-build and
    flush sketches are the same kind of claim -- a call chain restated in prose
    -- and arrived with the same exposure, so they arrive with the same gate.
    Order is the part a text search cannot see, so where a sketch asserts one
    (the module-loader phases) it is checked against the caller, not just
    against the set of names.
    """

    @staticmethod
    def _block(heading: str) -> str:
        """The first fenced block under ``heading``."""
        return DOC.split(heading, 1)[1].split("```", 2)[1]

    #: ``(name as written in the boot sketch, file, def-pattern)``.
    BOOT_CHAIN = (
        ("odoo.cli.main()", "cli/command.py", r"^def main\("),
        (
            "load_server_wide_modules()",
            "service/lifecycle.py",
            r"^def load_server_wide_modules\(",
        ),
        ("service.lifecycle.start()", "service/lifecycle.py", r"^def start\("),
        (
            "preload_registries(dbnames)",
            "service/lifecycle.py",
            r"^def preload_registries\(",
        ),
        ("Registry.new(", "orm/runtime/registry.py", r"^    def new\("),
    )

    def test_boot_chain_resolves(self) -> None:
        block = self._block("### Process boot")
        for written, rel, pattern in self.BOOT_CHAIN:
            self.assertIn(written, block, f"the boot sketch no longer names {written}")
            src = (ROOT / "odoo" / rel).read_text(encoding="utf-8")
            self.assertRegex(
                src, re.compile(pattern, re.MULTILINE), f"{rel}: {pattern}"
            )

    def test_the_three_server_classes_are_the_ones_start_chooses(self) -> None:
        """Named as a deployment choice, so the page must name all of them."""
        src = (ROOT / "odoo" / "service" / "lifecycle.py").read_text(encoding="utf-8")
        body = src.split("\ndef start(", 1)[1]
        chosen = {
            name
            for name in ("EventServer", "PreforkServer", "ThreadedServer")
            if f"{name}(" in body
        }
        self.assertEqual(
            chosen,
            {"EventServer", "PreforkServer", "ThreadedServer"},
            "service.lifecycle.start() no longer constructs all three servers",
        )
        block = self._block("### Process boot")
        for name in chosen:
            self.assertIn(name, block, f"the boot sketch dropped {name}")

    def test_bootstrap_order_matches_odoo_init(self) -> None:
        """``odoo/init.py`` is quoted *in order*; that order is the whole claim.

        The Rust probe has to run before the monkeypatches (a missing extension
        must fail with its own message, not inside a patched import), so a
        reordering here is a real regression rather than a wording change.
        """
        src = (ROOT / "odoo" / "init.py").read_text(encoding="utf-8")
        marks = [
            "MIN_PY_VERSION",
            "import odoo_rust",
            "__source_crc__",
            "gc.set_threshold",
            "patch_init",
        ]
        positions = []
        for mark in marks:
            index = src.find(mark)
            self.assertNotEqual(-1, index, f"odoo/init.py no longer does {mark}")
            positions.append(index)
        self.assertEqual(
            positions, sorted(positions), f"odoo/init.py reordered: {marks}"
        )

        # The page must list the same steps in the same order. Matching one
        # prose sentence instead only pinned the wording, so rewriting the
        # paragraph as a table -- same claim, better shape -- read as a
        # regression while a genuine reordering of the tail would not have.
        # The whole section, not self._block() -- that returns the fenced
        # sketch, and the bootstrap steps sit in a table beside it.
        section = DOC.split("### Process boot", 1)[1].split("\n### ", 1)[0]
        shown = [
            token
            for token in (
                "MIN_PY_VERSION",
                "odoo_rust",
                "__source_crc__",
                "GC threshold",
                "patch_init",
            )
            if token in section
        ]
        block = section
        self.assertEqual(
            shown,
            [
                "MIN_PY_VERSION",
                "odoo_rust",
                "__source_crc__",
                "GC threshold",
                "patch_init",
            ],
            "the boot sketch dropped a step or lists them out of order",
        )
        at = [block.index(token) for token in shown]
        self.assertEqual(at, sorted(at), "the boot sketch is out of init.py's order")

    @staticmethod
    def _loader_call_order() -> list[str]:
        """``loader.<phase>()`` calls in ``load_modules``, in source order."""
        src = (ROOT / "odoo" / "modules" / "loading.py").read_text(encoding="utf-8")
        body = src.split("\ndef load_modules(", 1)[1]
        return re.findall(r"loader\.(\w+)\(", body)

    def test_registry_build_phases_are_real_and_ordered(self) -> None:
        """Every phase named must be a ``_ModuleLoader`` method, in call order."""
        loading = (ROOT / "odoo" / "modules" / "loading.py").read_text(encoding="utf-8")
        methods = set(
            re.findall(
                r"^    def (\w+)\(",
                loading.split("\nclass _ModuleLoader", 1)[1],
                re.MULTILINE,
            )
        )
        self.assertTrue(methods, "_ModuleLoader has no methods; the split changed")

        block = self._block("### Registry build")
        named = [n for n in re.findall(r"\b(\w+)\(\)", block) if n in methods]
        self.assertTrue(
            named, "the registry-build sketch names no _ModuleLoader phase at all"
        )
        unknown = [
            n
            for n in re.findall(r"^\s*[├└]─ (\w+)\(", block, re.MULTILINE)
            if n not in methods and n not in {"setup_signaling", "load_modules"}
        ]
        self.assertEqual(unknown, [], f"phases that are not loader methods: {unknown}")

        order = self._loader_call_order()
        positions = [order.index(n) for n in named if n in order]
        self.assertEqual(len(positions), len(named), "a named phase is never called")
        self.assertEqual(
            positions,
            sorted(positions),
            "the registry-build sketch lists phases in an order load_modules "
            f"does not run them in: {named}",
        )

    def test_scenario_a_phase_table_is_ordered_and_says_it_is_partial(self) -> None:
        """The other phase list — same claim, and it had no gate.

        ``runtime.md``'s sketch is pinned by the test above; ``scenarios.md``
        numbers its phases 1..N in a table, which reads as an enumeration rather
        than a selection, and nothing checked it. The two lists are different
        selections from the same 22 calls — ``runtime.md`` omits
        ``untranslate_dropped_fields``, the table omits ``validate_custom_views``
        and ``register_model_hooks`` — and both are in call order, which is the
        claim that matters. So: order is enforced, completeness is not, and each
        list has to say it is a selection so a reader does not take the numbering
        for the whole sequence.
        """
        order = self._loader_call_order()
        self.assertGreater(len(order), 15, "load_modules no longer calls phases")

        table = DOC.split("## Scenario A — installing a module", 1)[1].split(
            "\n\n##", 1
        )[0]
        named = [n for n in re.findall(r"\| `(\w+)\(\)`", table) if n in order]
        self.assertGreater(len(named), 5, "the scenario table names no phases")
        positions = [order.index(n) for n in named]
        self.assertEqual(
            positions,
            sorted(positions),
            f"the Scenario A table is out of call order: {named}",
        )
        # Both lists must admit they are partial, and by the live total.
        self.assertIn(f"{len(order)} calls", DOC_FLAT, "the full phase count is stated")

    def test_the_reload_reentry_is_real(self) -> None:
        """ "may force one full reload" — the loop really does re-enter Registry.new."""
        self.assertIn("may force one full reload", DOC)
        src = (ROOT / "odoo" / "modules" / "loading.py").read_text(encoding="utf-8")
        handler = src.split("except _UninstallRequiresReload:", 1)
        self.assertEqual(
            len(handler), 2, "_UninstallRequiresReload is no longer caught"
        )
        self.assertIn("Registry.new(", handler[1].split("\n\n", 1)[0])

    def test_transaction_owns_what_the_sketch_draws(self) -> None:
        """Each branch of the transaction diagram must be a ``Transaction`` slot."""
        block = self._block("### Transaction, cache and flush")
        drawn = re.findall(r"^\s*[├└]─ (\w+)\s", block, re.MULTILINE)
        self.assertTrue(drawn, "the transaction sketch draws no members")
        src = (ROOT / "odoo" / "orm" / "runtime" / "transaction.py").read_text(
            encoding="utf-8"
        )
        slots = set(re.findall(r'"(\w+)"', src.split("__slots__ = (", 1)[1]))
        missing = [name for name in drawn if name not in slots]
        self.assertEqual(missing, [], f"not Transaction slots: {missing}")

    def test_environment_interning_claim(self) -> None:
        """ "interned per (cr, uid, su, context)" — the lookup must exist."""
        self.assertIn("is **interned** per `(cr, uid, su, context)`", DOC_FLAT)
        src = (ROOT / "odoo" / "orm" / "runtime" / "environment.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("envs.lookup(envs.key(uid, su, frozen_context))", src)

    def test_flush_loop_names_and_cap(self) -> None:
        """The fixpoint cap is quoted as a number, so re-derive it."""
        match = re.search(r"MAX_FIXPOINT_ITERATIONS`? \((\d+)\)", DOC_FLAT)
        self.assertIsNotNone(match, "the fixpoint cap is no longer stated")
        transaction = (ROOT / "odoo" / "orm" / "runtime" / "transaction.py").read_text(
            encoding="utf-8"
        )
        declared = re.search(
            r"^MAX_FIXPOINT_ITERATIONS = (\d+)", transaction, re.MULTILINE
        )
        self.assertIsNotNone(declared, "MAX_FIXPOINT_ITERATIONS moved")
        self.assertEqual(int(match.group(1)), int(declared.group(1)))

    def test_flush_entry_points_exist(self) -> None:
        env = (ROOT / "odoo" / "orm" / "runtime" / "environment.py").read_text(
            encoding="utf-8"
        )
        uow = (ROOT / "odoo" / "orm" / "components" / "unit_of_work.py").read_text(
            encoding="utf-8"
        )
        recompute = (
            ROOT / "odoo" / "orm" / "models" / "mixins" / "recompute.py"
        ).read_text(encoding="utf-8")
        for name, src in (
            ("run_flush_loop", uow),
            ("flush_model", recompute),
            ("_flush", recompute),
        ):
            # Not backtick-anchored: most of these are named inside the fenced
            # sketch, where the page (rightly) does not backtick anything.
            self.assertIn(name, DOC, f"the flush sketch dropped {name}")
            self.assertRegex(src, re.compile(rf"^    def {name}\b", re.MULTILINE))
        self.assertIn("flush_all()", DOC)
        self.assertRegex(env, re.compile(r"^    def flush_all\b", re.MULTILINE))
        # The pipeline and the escape hatch are both stated; both are real.
        self.assertIn("`tolerant_recompute`", DOC)
        self.assertIn('context.get("tolerant_recompute")', env)
        self.assertIn("cr.pipeline()", DOC)
        self.assertIn("with self.cr.pipeline():", env)


class TestContractNamesResolveEverywhere(unittest.TestCase):
    """A contract cited outside the rules table must still be a contract.

    The blueprint tables (ownership, "where to add code") name contracts far
    from the table that defines them, which is exactly the shape that rots: a
    renamed contract stays right in one place and wrong in three. Checked
    globally rather than per-table so a fourth citation is covered for free.
    """

    def test_every_kebab_case_citation_is_a_real_contract(self) -> None:
        known = {c.name for c in layer_check.CONTRACTS}
        # Whole backtick spans only, and at least two hyphens: enough to
        # exclude ordinary hyphenated prose (`pre-push`) without listing
        # exceptions, since every contract name has three or more.
        cited = set(re.findall(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+){2,})`", DOC))
        self.assertTrue(cited, "the page cites no contract; the pattern has rotted")
        self.assertEqual(
            cited - known,
            set(),
            f"backticked kebab-case names that are not contracts: "
            f"{sorted(cited - known)}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
