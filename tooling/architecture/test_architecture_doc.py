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
    _ARCH_DOCS / "findings.md",
)
for _p in DOC_PATHS:
    if not _p.is_file():
        raise AssertionError(
            f"architecture document missing: {_p.relative_to(ROOT)} — this suite "
            f"pins the whole set, so a missing file is a broken gate, not a "
            f"lighter one"
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
    "twenty-two": 22,
    "twenty-three": 23,
    "twenty-four": 24,
    "twenty-five": 25,
    "twenty-six": 26,
}


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

    def test_page_no_longer_advertises_a_divergence(self) -> None:
        """The page said the docstring omits things; it must not still say so."""
        self.assertIn("Both now name every member at the layer the gate", DOC_FLAT)


class TestMixinGraphProse(unittest.TestCase):
    """Claims about the shape of the mixin ``self``-call graph.

    These are the page's least checkable-looking sentences and its most
    load-bearing: the whole "the import graph cannot see this" section exists
    to justify a second gate. Both bugs found here were of the same kind — a
    sentence that stayed true in spirit while the graph moved underneath it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        import mixin_coupling_check as mcc

        cls.units = mcc.collect_units()
        cls.edges, _ = mcc.build_edges(cls.units)

    def test_graph_really_is_a_dag_through_self(self) -> None:
        """The page states this outright, so it must be measured, not assumed."""
        self.assertIn("**Through `self`, the graph is a DAG.**", DOC_FLAT)
        self.assertIn("`cyclic_edges` is 0", DOC_FLAT)
        import mixin_coupling_check as mcc

        measured = mcc.measure()
        self.assertEqual(0, measured["cyclic_edges"])
        self.assertEqual(1, measured["max_scc"], "a cycle is back")

    def test_graph_is_also_a_dag_through_recordsets(self) -> None:
        """The other half, and the one the page used to omit entirely.

        The page claimed the composition was a DAG on the strength of the
        ``self``-only graph. Measuring the recordset-mediated edges found a
        cycle (``base.py`` ⇄ ``create``); extracting ``_ConstraintsMixin``
        removed it. Pinned at zero so neither the prose nor the graph can move
        without the other.
        """
        self.assertIn("**Through the model, it is too", DOC_FLAT)
        self.assertIn("**`base.py` ⇄ `create`**", DOC_FLAT)
        import mixin_coupling_check as mcc

        measured = mcc.measure(through_recordsets=True)
        self.assertEqual(0, measured["cyclic_edges"], "a recordset cycle is back")
        self.assertEqual(1, measured["max_scc"])
        self.assertEqual([], measured["sccs"])

    def test_the_recordset_graph_is_strictly_wider(self) -> None:
        """It must actually see more, or ratcheting it proves nothing."""
        import mixin_coupling_check as mcc

        narrow = mcc.measure()
        wide = mcc.measure(through_recordsets=True)
        self.assertGreater(
            wide["edges_total"],
            narrow["edges_total"],
            "recordset-mediated calls are no longer being detected",
        )

    def test_both_views_are_ratcheted(self) -> None:
        """A number the page cites as a floor must actually be one."""
        import mixin_coupling_check as mcc

        for key in ("max_scc", "cyclic_edges", "scc_without_base"):
            self.assertIn(key, mcc.BASELINE)
            self.assertIn(f"recordset_{key}", mcc.BASELINE)
        self.assertIn("`recordset_max_scc` 1", DOC_FLAT)
        self.assertIn("`recordset_cyclic_edges` 0", DOC_FLAT)

    def test_read_search_backedge_is_the_one_that_went(self) -> None:
        """ "read ⇄ search, back-edge only" — both halves.

        The first wording said the two units no longer call each other. They
        do: ``search -> read`` survives and is a perfectly good DAG edge. Only
        ``read -> search`` went.
        """
        self.assertIn("back-edge `read → search` is gone", DOC_FLAT)
        self.assertIn("`search → read` is still there", DOC_FLAT)
        self.assertNotIn("search", self.edges.get("read", {}))
        self.assertIn("read", self.edges.get("search", {}))

    def test_query_dependant_count(self) -> None:
        stated = re.search(r"(\w+) units depend on `_query`", DOC_FLAT)
        self.assertIsNotNone(stated, "the _query fan-in is no longer stated")
        words = {"three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
        dependants = [n for n, targets in self.edges.items() if "_query" in targets]
        self.assertEqual(words[stated.group(1).lower()], len(dependants))
        self.assertEqual(
            {"read", "search", "recompute"},
            set(dependants) - {n for n in dependants if n.startswith("read_group/")},
        )

    def test_documented_explain_example_demonstrates_an_edge(self) -> None:
        """A ``--explain A B`` in the docs must name a pair that has an edge.

        The example was ``--explain read search``, chosen when that was the
        cycle. After ``_query`` landed it printed "no edge read -> search" — a
        documented command whose output is the absence of the thing it is
        supposed to illustrate.
        """
        example = re.search(r"mixin_coupling_check\.py --explain (\w+) (\w+)", DOC)
        self.assertIsNotNone(example, "the --explain example is gone")
        source, target = example.groups()
        self.assertIn(source, self.units, f"--explain example names unknown {source}")
        self.assertIn(target, self.units, f"--explain example names unknown {target}")
        self.assertIn(
            target,
            self.edges.get(source, {}),
            f"the documented example `--explain {source} {target}` has no edge to "
            "show; pick a pair that does",
        )


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

    def test_layer1_bullet_admits_the_non_orm_imports(self) -> None:
        """``fields``/``domain`` import odoo.tools & co; "only Layer 0" misled."""
        imports = self._orm_imports("fields") | self._orm_imports("domain")
        self.assertTrue(
            any(i.startswith("odoo.tools") for i in imports),
            "Layer 1 no longer imports odoo.tools; the bullet can be simplified",
        )
        self.assertIn("both packages import `odoo.tools`", DOC_FLAT)

    def test_layer1_really_avoids_components(self) -> None:
        """The bullet's positive claim: Layer 1 imports components/ nowhere."""
        self.assertIn("Layer 1 imports `components/` nowhere", DOC_FLAT)
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

    def test_ratchet_baselines_match_documented_gates(self) -> None:
        match = re.search(
            r"turns (\w+) tool\s+counts into one-way contracts: "
            r"\*\*mypy, ruff, ruff_docstring, c901, c901_addons, eslint, tsc, "
            r"jsfunclen, jsprivate, jsserviceshape and naming\*\*",
            DOC,
        )
        self.assertIsNotNone(match, "the ratchet gate list is no longer stated")
        on_disk = {
            p.stem for p in (ROOT / "tooling" / "ratchet" / "baselines").glob("*.json")
        }
        self.assertEqual(
            {"mypy", "ruff", "ruff_docstring", "c901", "c901_addons", "eslint",
             "tsc", "jsfunclen", "jsprivate", "jsserviceshape", "naming"},
            on_disk,
        )
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
        self.assertIn("runtime/backend.py::InMemoryBackend", DOC)
        src = (ROOT / "odoo" / "orm" / "runtime" / "backend.py").read_text(
            encoding="utf-8"
        )
        self.assertRegex(src, re.compile(r"^class InMemoryBackend\b", re.MULTILINE))

    def test_env_core_facade(self) -> None:
        self.assertIn("`OrmCore`, defined in `components/core.py`", DOC_FLAT)
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
        self.assertIn("no longer sniffs the test backend via", DOC_FLAT)
        scopes = [
            ROOT / "odoo" / "orm" / "models" / "mixins",
            ROOT / "odoo" / "orm" / "fields",
        ]
        offenders = [
            (p.relative_to(ROOT), needle)
            for directory in scopes
            for p in directory.rglob("*.py")
            for needle in ("transaction.storage", "backend is None", "backend is not None")
            if needle in p.read_text(encoding="utf-8")
        ]
        self.assertEqual([], offenders)

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

    def test_env_private_member_counts_are_measured(self) -> None:
        buckets = self._env_by_package()
        layer1 = len(buckets["Layer 1"]["prv"])
        layer2 = len(buckets["Layer 2"]["prv"])
        self.assertIn(
            f"({layer1} unsanctioned private members against {layer2},",
            DOC_FLAT,
            f"the page's env private-member figures disagree with a live run "
            f"(Layer 1 has {layer1}, Layer 2 has {layer2})",
        )

    def test_env_access_counts_are_measured(self) -> None:
        """Accesses, not pinned entries.

        ``KNOWN_VIOLATIONS`` is keyed by ``(path, attr)``, so its length counts
        6 and 2 -- one entry covers all four ``base.py`` reaches of
        ``_field_cache_memo``. The page quotes *sites*, which only a run knows.
        """
        import env_surface_check

        sanctioned = set(env_surface_check.SANCTIONED_PRIVATE)
        by_layer: dict[str, int] = {}
        for reach in env_surface_check.check().reaches:
            if reach.is_private and reach.attr not in sanctioned:
                by_layer[reach.layer] = by_layer.get(reach.layer, 0) + 1
        self.assertIn(
            f"{by_layer['Layer 1']} accesses against {by_layer['Layer 2']})", DOC_FLAT
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

    def test_pool_figures_are_measured(self) -> None:
        import pool_surface_check

        report = pool_surface_check.check()
        sites: dict[str, int] = {}
        members: dict[str, set[str]] = {}
        subscripts: dict[str, int] = {}
        for reach in report.reaches:
            sites[reach.layer] = sites.get(reach.layer, 0) + 1
            members.setdefault(reach.layer, set()).add(reach.attr)
            subscripts[reach.layer] = subscripts.get(reach.layer, 0) + reach.subscript
        self.assertIn(
            f"touches the Registry at {sites['Layer 1']} sites against "
            f"`orm/models`' {sites['Layer 2']}**",
            DOC_FLAT,
        )
        # Both counts, measured. This asserted a literal ``Layer 2 == 0``, which
        # was true only while Layer 2's scope was ``orm/models`` alone; widening
        # it to the ORM modules that were in no scope at all (``registration``,
        # ``helpers``, …) gave Layer 2 subscripts of its own. A hardcoded zero
        # in a suite whose whole premise is "figures come from a live run" is
        # the same restated-number bug one level down.
        self.assertIn(
            f"uses {subscripts['Layer 1']} `pool[<model>]` subscripts against "
            f"Layer 2's {subscripts.get('Layer 2', 0)}",
            DOC_FLAT,
        )

    def test_pool_member_width_inversion_is_stated(self) -> None:
        """Layer 2 is *wider* by distinct member; the page must not claim otherwise."""
        import pool_surface_check

        report = pool_surface_check.check()
        members: dict[str, set[str]] = {}
        privates: dict[str, set[str]] = {}
        for reach in report.reaches:
            # ``pool[...]`` is recorded as ``__getitem__``: the Mapping protocol
            # Registry implements, not a member of its surface. The checker's own
            # report excludes it from the member list and counts it as a
            # subscript, so the page's figures must exclude it too.
            if reach.attr.startswith("__"):
                continue
            members.setdefault(reach.layer, set()).add(reach.attr)
            if reach.is_private:
                privates.setdefault(reach.layer, set()).add(reach.attr)
        self.assertGreater(
            len(members["Layer 2"]),
            len(members["Layer 1"]),
            "Layer 2 is no longer the wider consumer; rewrite the paragraph",
        )
        self.assertIn(
            f"reaches *more distinct* members than Layer 1 ({len(members['Layer 2'])} "
            f"against {len(members['Layer 1'])})",
            DOC_FLAT,
        )
        self.assertTrue(privates.get("Layer 2"), "Layer 2 has no private reach left")
        for attr in privates["Layer 2"]:
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

    def test_stated_count_matches_both(self) -> None:
        words = {
            12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
            22: "twenty-two", 23: "twenty-three", 24: "twenty-four",
            25: "twenty-five", 26: "twenty-six",
        }
        count = len(self._workflow_gates())
        self.assertIn(
            f"runs **{words[count]}** blocking checkers", DOC_FLAT, f"{count} gates run"
        )

    def test_every_gate_step_is_blocking(self) -> None:
        """A step that does not re-raise its exit code is a gate that cannot fail."""
        # Two idioms re-raise a gate's status: the original
        # `exit "${GATE_EXIT}"` and the `exit $rc` used by the steps that pipe a
        # count into tooling/ratchet. Both are blocking; counting only the first
        # read eleven live gates as unwired.
        reraised = self.yaml.count('exit "${GATE_EXIT}"') + self.yaml.count("exit $rc")
        self.assertEqual(reraised, len(self._workflow_gates()))

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
        """``cross_repo_coherence.py`` is "an Nth checker" — N must track the table."""
        words = {
            12: "twelfth", 13: "thirteenth", 14: "fourteenth", 15: "fifteenth",
            23: "twenty-third", 24: "twenty-fourth", 25: "twenty-fifth",
            26: "twenty-sixth", 27: "twenty-seventh",
        }
        expected = words[len(self._workflow_gates()) + 1]
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
        cites = re.findall(r"`([\w/]+\.py):(\d+)`", DOC)
        self.assertTrue(cites, "no line citations found; the regex has rotted")
        for name, lineno in cites:
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
        import py_cycle_check

        report = py_cycle_check.check()
        packages = {
            cycle[0].split(".")[1]
            for cycle in getattr(report, "known", None) or report.cycles
        }
        # Derived from the run, not restated: the set used to be hardcoded to
        # three, so restoring ``odoo/tests/`` to the graph — the shipped test
        # FRAMEWORK, dropped wholesale by a directory-name filter — turned a
        # correct widening of the gate's coverage into a red build.
        self.assertEqual(packages, {"service", "modules", "cli", "tests"})
        count = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}[len(packages)]
        named = ", ".join(f"`{p}`" for p in ("service", "modules", "cli", "tests"))
        self.assertIn(f"{count} are pinned ({named}", DOC_FLAT.replace("—", "-"))

    def test_the_orm_really_has_no_cycle(self) -> None:
        """ "the ORM has none" is the load-bearing half of that sentence."""
        import py_cycle_check

        report = py_cycle_check.check()
        orm = [c for c in report.cycles if any(m.startswith("odoo.orm") for m in c)]
        self.assertEqual(orm, [], "the ORM has a cycle; the page says it has none")
        self.assertIn("the ORM has none", DOC_FLAT)

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

    LAYER0 = ("primitives", "parsing", "validation", "constants", "_typing")

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
        bullet = DOC_FLAT.split("**Layer 0** imports no higher", 1)[1][:900]
        for dotted in contract.forbidden:
            wanted = dotted if dotted in facades else dotted.removeprefix("odoo.")
            self.assertIn(
                f"`{wanted}`",
                bullet,
                f"the Layer-0 bullet does not name {dotted}",
            )


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
        self.assertIn("`MIN_PY_VERSION`, probe the mandatory `odoo_rust`", DOC_FLAT)
        src = (ROOT / "odoo" / "init.py").read_text(encoding="utf-8")
        marks = ["MIN_PY_VERSION", "import odoo_rust", "gc.set_threshold", "patch_init"]
        positions = []
        for mark in marks:
            index = src.find(mark)
            self.assertNotEqual(-1, index, f"odoo/init.py no longer does {mark}")
            positions.append(index)
        self.assertEqual(
            positions, sorted(positions), f"odoo/init.py reordered: {marks}"
        )

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
