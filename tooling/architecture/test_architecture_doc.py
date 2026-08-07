#!/usr/bin/env python3
"""Fact-check ``odoo/ARCHITECTURE.md`` against the code it describes.

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
DOC_PATH = ROOT / "odoo" / "ARCHITECTURE.md"
DOC = DOC_PATH.read_text(encoding="utf-8")

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
    """The Identity section's headline claim: the monoliths are decomposed.

    It names six files. Five are now packages or gone; ``service/server.py``
    survives as a re-export facade. That is the page's whole premise — every
    layering rule below it exists because those files were split — so it is
    worth asserting rather than assuming.
    """

    def test_named_monoliths_are_no_longer_monoliths(self) -> None:
        listed = re.search(
            r"the monoliths \((.*?)\) have been\s*\n?\s*decomposed", DOC, re.DOTALL
        )
        self.assertIsNotNone(listed, "the Posture bullet no longer names the files")
        names = re.findall(r"`([\w/.]+\.py)`", listed.group(1))
        self.assertEqual(6, len(names), f"expected six named files, got {names}")

        for name in names:
            path = ROOT / "odoo" / name
            if not path.exists():
                continue  # e.g. sql_db.py, replaced wholesale by db/
            if path.is_file():
                # Survivors are allowed, but only as thin facades. server.py is
                # 81 lines of re-exports; a monolith would be thousands.
                lines = len(path.read_text(encoding="utf-8").splitlines())
                self.assertLess(
                    lines,
                    400,
                    f"odoo/{name} is {lines} lines — the page calls it decomposed",
                )
            else:
                self.assertTrue(
                    (path / "__init__.py").is_file(),
                    f"odoo/{name} is a directory but not a package",
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
        self.assertFalse(missing, f"original boundary dropped from the table: {missing}")
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
        self.assertEqual((3, 14), self.consts["MIN_PY_VERSION"])
        self.assertEqual((3, 14), self.consts["MAX_PY_VERSION"])
        self.assertIn(
            "Python 3.14 (`MIN_PY_VERSION` = `MAX_PY_VERSION` = 3.14)", DOC_FLAT
        )

    def test_postgres_floor(self) -> None:
        match = re.search(r"PostgreSQL ≥ (\d+) \(`MIN_PG_VERSION`\)", DOC)
        self.assertIsNotNone(match, "the PG floor is no longer stated with its const")
        self.assertEqual(int(match.group(1)), self.consts["MIN_PG_VERSION"])


class TestReferencedArtifacts(unittest.TestCase):
    """Every ADR, script and module path named on the page must exist."""

    def test_adrs_exist(self) -> None:
        adr_dir = ROOT / "doc" / "adr"
        for number in sorted(set(re.findall(r"ADR-(\d{4})", DOC))):
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
        for script in re.findall(r"^python (\S+\.py)", DOC, re.MULTILINE):
            self.assertTrue(
                (ROOT / script).is_file(),
                f"ARCHITECTURE.md documents `python {script}`, which is missing",
            )

    def test_referenced_workflows_exist(self) -> None:
        for wf in re.findall(r"`\.github/workflows/([\w.-]+\.yml)`", DOC):
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

        stated = re.search(r"workflow runs \*\*(\w+)\*\* blocking checkers", DOC)
        self.assertIsNotNone(stated, "the gate count is no longer stated")
        words = {
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12,
        }
        self.assertEqual(words[stated.group(1)], len(run_in_ci))

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
        match = re.search(r"\*\*mypy, ruff, eslint and tsc\*\*", DOC)
        self.assertIsNotNone(match, "the ratchet gate list is no longer stated")
        on_disk = {
            p.stem for p in (ROOT / "tooling" / "ratchet" / "baselines").glob("*.json")
        }
        self.assertEqual({"mypy", "ruff", "eslint", "tsc"}, on_disk)

    def test_named_source_paths_exist(self) -> None:
        """Backticked ``odoo/...`` and ``tooling/...`` paths must resolve.

        The page mixes two bases — ``tooling/...`` is repo-relative while
        ``libs/...``, ``addons/base/...`` etc. are relative to ``odoo/``, because
        that is the package the page is about. Both are tried, and a bare module
        name is allowed to resolve as ``<name>.py``. Globs are skipped.
        """
        pattern = r"`((?:odoo|tooling|doc|addons|libs|orm|db|http|service)/[\w./-]+?)`"
        for raw in sorted(set(re.findall(pattern, DOC))):
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

    def test_transaction_storage_sniffing_is_gone(self) -> None:
        """ADR-0011's claim: production CRUD no longer reads transaction.storage."""
        self.assertIn("no longer sniffs the test backend via", DOC_FLAT)
        mixins = ROOT / "odoo" / "orm" / "models" / "mixins"
        offenders = [
            p.relative_to(ROOT)
            for p in mixins.rglob("*.py")
            if "transaction.storage" in p.read_text(encoding="utf-8")
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
        for kept in ("asset_log", "constants"):
            self.assertTrue((ROOT / "odoo" / "libs" / f"{kept}.py").is_file())


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
