#!/usr/bin/env python3


from __future__ import annotations

import ast
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import doc_restated_counts
import layer_check
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="test_architecture_doc")

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

    return "\n\n".join(p.read_text(encoding="utf-8") for p in DOC_PATHS)


DOC = read_docs()

DOC_FLAT = " ".join(DOC.split())


def _class_bases(source: Path, class_name: str) -> list[str]:

    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [b.id for b in node.bases if isinstance(b, ast.Name)]
    raise AssertionError(f"class {class_name} not found in {source}")


def _imported_modules(source: Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


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

NUMBER_WORD_BY_VALUE = {value: word for word, value in NUMBER_WORDS.items()}


class TestMixinCount(unittest.TestCase):
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
        match = re.search(r"— (\d+) public .*? plus (\d+) private", DOC, re.DOTALL)
        self.assertIsNotNone(match, "coupling section no longer states the split")
        public, private = int(match.group(1)), int(match.group(2))
        self.assertEqual(public, sum(not b.startswith("_") for b in self.bases))
        self.assertEqual(private, sum(b.startswith("_") for b in self.bases))
        self.assertEqual(public + private, len(self.bases))

    def test_unit_count_and_read_group_share(self) -> None:

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
    def setUp(self) -> None:
        self.bases = _class_bases(
            ROOT / "odoo" / "orm" / "models" / "base.py", "BaseModel"
        )

    COUNT_PATTERNS = (
        r"(\d+) ``__slots__ = \(\)`` mixins",
        r"BaseModel's (\d+) mixins",
    )

    def _mixin_counts_in(self, rel: str) -> list[int]:
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


class TestPosture(unittest.TestCase):
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
        self.assertFalse((ROOT / "odoo" / "sql_db.py").exists())
        self.assertTrue((ROOT / "odoo" / "db" / "__init__.py").is_file())


class TestOrmDocstringAgreesWithGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        src = (ROOT / "odoo" / "orm" / "__init__.py").read_text(encoding="utf-8")
        cls.docstring = ast.get_docstring(ast.parse(src)) or ""

    def _section(self, heading: str) -> str:
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

        self.assertIn(
            "Where a doc and the gate differ, `layer_check.py`'s `CONTRACTS` "
            "wins — it is the definition that runs.",
            DOC_FLAT,
        )


class TestCompositionTable(unittest.TestCase):
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
        rows: dict[str, list[str]] = {}
        for line in DOC.splitlines():
            match = re.match(r"^\| `(\w+)` \(`[^`]+`\) \|(.+)\|$", line)
            if match:
                rows[match.group(1)] = [c.strip() for c in match.group(2).split("|")]
        return rows

    def _root_dominates(self, comp) -> bool:

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

        self.assertEqual(
            sorted(c.label for c in self.mcc.COMPOSITIONS),
            sorted(self.rows),
            "the composition table and COMPOSITIONS disagree",
        )
        self.assertEqual(5, len(self.mcc.COMPOSITIONS))

    def test_the_table_header_is_the_one_this_test_parses(self) -> None:
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
        for comp in self.mcc.COMPOSITIONS:
            self.assertEqual(
                0,
                self.mcc.measure(comp=comp)["cyclic_edges"],
                f"{comp.label} is no longer a DAG",
            )
            self.assertEqual("0", self.rows[comp.label][2])

    def test_the_ratchet_backs_every_column_that_can_regress(self) -> None:
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
        aware = {c.label for c in self.mcc.COMPOSITIONS if c.recordset_aware}
        self.assertEqual({"BaseModel"}, aware)

    def test_units_are_file_level_not_bases(self) -> None:
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
        registry_src = (
            self.mcc.ROOT / "odoo" / "orm" / "runtime" / "_registry_models.py"
        ).read_text(encoding="utf-8")
        self.assertIn("models: dict[str, type[BaseModel]]", registry_src)

    def test_discovery_finds_exactly_the_documented_set(self) -> None:

        self.assertIn("discovers composition roots from the tree", DOC_FLAT)
        self.assertEqual(
            {"BaseModel", "Field", "Registry", "Request", "Cursor"},
            {c.root_class for c in self.mcc.COMPOSITIONS},
        )

    def test_the_documented_explain_example_demonstrates_an_edge(self) -> None:

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

        self.assertIn(
            "that contract is clean, because the reach arrives through `env` "
            "and produces no import edge",
            DOC_FLAT,
        )
        source = self.SOURCE.read_text(encoding="utf-8")
        for banned in ("from odoo.orm", "import odoo.orm"):
            self.assertNotIn(banned, source)


class TestToolsIsTheFacadeForLibs(unittest.TestCase):
    TOOLS = ROOT / "odoo" / "tools"

    @staticmethod
    def _import_sources(tree: ast.Module) -> dict[str, str]:
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
        for symbol in ("SQL", "float_round", "classproperty", "make_index_name"):
            self.assertIn(symbol, direct)

    def test_the_transitive_count_is_live(self) -> None:
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
        self.assertLessEqual({"html_escape", "single_email_re"}, from_libs)


class TestLayerProse(unittest.TestCase):
    def _orm_imports(self, package: str) -> set[str]:
        pkg = ROOT / "odoo" / "orm" / package
        names: set[str] = set()
        for path in pkg.rglob("*.py"):
            if "tests" in path.relative_to(pkg).parts:
                continue
            names |= _imported_modules(path)
            names |= {
                f"odoo.orm.{m}"
                for m in re.findall(
                    r"^from \.+(\w+)", path.read_text(encoding="utf-8"), re.MULTILINE
                )
            }
        return names

    def test_the_table_admits_the_non_orm_imports(self) -> None:

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
        self.assertIn("| Imports `components/` nowhere |", DOC)
        imports = self._orm_imports("fields") | self._orm_imports("domain")
        self.assertEqual(
            set(),
            {i for i in imports if "components" in i},
            "Layer 1 now imports orm/components; the bullet is wrong",
        )

    def test_layer2_components_dependency_is_named(self) -> None:
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
    def _table_rows(self) -> list[str]:
        section = DOC.split("## Enforced dependency rules", 1)[1]
        section = section.split("**The eight original boundaries", 1)[0]
        return re.findall(r"^\| `([a-z0-9-]+)` \|", section, re.MULTILINE)

    def test_names_match_checker(self) -> None:

        rows = self._table_rows()
        self.assertEqual(len(rows), len(set(rows)), "duplicate row in the table")
        self.assertEqual(set(rows), {c.name for c in layer_check.CONTRACTS})

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
        rows = self._table_rows()
        self.assertEqual(8, len(self.ORIGINAL_EIGHT))
        missing = self.ORIGINAL_EIGHT - set(rows)
        self.assertFalse(
            missing, f"original boundary dropped from the table: {missing}"
        )
        self.assertIn("**The eight original boundaries are clean at zero**", DOC)

    def test_later_contracts_are_also_in_the_table(self) -> None:

        rows = set(self._table_rows())
        later = {c.name for c in layer_check.CONTRACTS} - self.ORIGINAL_EIGHT
        self.assertTrue(later, "expected contracts beyond the original eight")
        self.assertFalse(later - rows, f"undocumented contract(s): {later - rows}")

    def test_components_row_admits_the_libs_exception(self) -> None:
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
        new, _known = layer_check.check()
        self.assertEqual([], new, "ARCHITECTURE.md claims 0 new violations")

    def test_pinned_rules_are_scoped_to_service(self) -> None:
        self.assertIn("scoped to `odoo.service`", DOC_FLAT)
        for known in layer_check.KNOWN_VIOLATIONS:
            self.assertEqual("odoo.service", known.module)

    def test_tests_exemption_is_documented(self) -> None:
        self.assertIn("CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT", DOC_FLAT)
        self.assertEqual(
            {"tests"}, set(layer_check.CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT)
        )

    def test_test_files_are_really_skipped(self) -> None:
        self.assertIn("Test files are not scanned", DOC_FLAT)
        self.assertTrue(layer_check._is_test_file(Path("odoo/orm/tests/test_x.py")))
        self.assertTrue(layer_check._is_test_file(Path("odoo/db/conftest.py")))
        self.assertFalse(layer_check._is_test_file(Path("odoo/db/pool.py")))


class TestRuntimeFloors(unittest.TestCase):
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

        self.assertEqual(self.consts["MIN_PY_VERSION"], self.consts["MAX_PY_VERSION"])
        self.assertIn("`MIN_PY_VERSION`", DOC)
        init = (ROOT / "odoo" / "init.py").read_text(encoding="utf-8")
        self.assertIn("if sys.version_info[:2] < MIN_PY_VERSION:", init)

    def test_postgres_floor(self) -> None:
        self.assertIsInstance(self.consts["MIN_PG_VERSION"], int)
        self.assertIn("`MIN_PG_VERSION`", DOC)
        self.assertIn("`PoolError`", DOC)
        pool = (ROOT / "odoo" / "db" / "pool.py").read_text(encoding="utf-8")
        self.assertIn("from odoo.release import MIN_PG_VERSION", pool)
        self.assertIn("raise PoolError(", pool.split("sv < MIN_PG_VERSION")[1])


class TestReferencedArtifacts(unittest.TestCase):
    def test_adrs_exist(self) -> None:
        adr_dir = ROOT / "doc" / "adr"
        numbers = sorted(set(re.findall(r"ADR-(\d{4})", DOC)))
        self.assertTrue(numbers, "the page cites no ADR; the pattern has rotted")
        for number in numbers:
            self.assertTrue(
                list(adr_dir.glob(f"{number}-*.md")),
                f"ARCHITECTURE.md references ADR-{number}, which does not exist",
            )

    def test_adr_range_is_complete(self) -> None:

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

        workflow = (ROOT / ".github" / "workflows" / "architecture.yml").read_text(
            encoding="utf-8"
        )
        pr_block = workflow.split("pull_request:", 1)[1].split("permissions:", 1)[0]
        globs = re.findall(r"^\s*- '([^']+)'", pr_block, re.MULTILINE)
        self.assertTrue(globs, "the pull_request path filter is empty")

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
        driven: set[str] = set()
        for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
            driven.update(
                re.findall(
                    r"ratchet\.py (\w+)(?: --mode [\w-]+)? --count",
                    workflow.read_text(encoding="utf-8"),
                )
            )
        return driven

    def test_ratchet_baselines_match_documented_gates(self) -> None:

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
        self.assertEqual(
            NUMBER_WORDS[match.group(1)],
            len(on_disk),
            "the ratchet gate list and the count in front of it disagree",
        )

    def test_named_source_paths_exist(self) -> None:

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
    def _map_block(self) -> str:
        return DOC.split("## Subsystem map", 1)[1].split("```", 2)[1]

    def _modules_on_disk(self, package: str) -> set[str]:
        pkg = ROOT / "odoo" / package
        return {p.stem for p in pkg.glob("*.py") if p.stem != "__init__"} - {"tests"}

    def _listed_in(self, package: str, next_package: str) -> set[str]:

        block = self._map_block().split(f"── {package}/", 1)[1]
        block = block.split(f"── {next_package}/", 1)[0]
        body = block.split("\n", 1)[1]
        while True:
            stripped = re.sub(r"\([^()]*\)", " ", body)
            if stripped == body:
                break
            body = stripped
        body = re.sub(r"\[[^\]]*\]", " ", body)
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
        self.assertIn("the handler runs a second time", DOC_FLAT)
        src = (ROOT / "odoo" / "http" / "_serve.py").read_text(encoding="utf-8")
        self.assertIn("psycopg.errors.ReadOnlySqlTransaction", src)

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
        init = ROOT / "odoo" / "addons" / "test_http" / "tests" / "__init__.py"
        self.assertIn("from . import test_lifecycle_order", init.read_text())

    def test_the_page_names_where_the_proof_is(self) -> None:
        self.assertIn("test_lifecycle_order.py", DOC_FLAT)


class TestSeams(unittest.TestCase):
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

        for line in DOC.splitlines():
            if "backend" not in line.lower():
                continue
            self.assertNotRegex(
                line,
                r"None\s*=\s*Postgre|backend\s+is\s+None",
                "a view still describes env.backend as None for PostgreSQL",
            )
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
        self.assertTrue((ROOT / "odoo" / "libs" / "asset_log.py").is_file())
        self.assertFalse((ROOT / "odoo" / "libs" / "constants.py").is_file())
        for relocated in ("tools/assets/constants", "tools/constants"):
            self.assertTrue((ROOT / "odoo" / f"{relocated}.py").is_file())


class TestCronExceptionRationale(unittest.TestCase):
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

    INVERSION_ROWS = (
        "`Registry` accesses",
        "`pool[<model>]` subscripts",
        "distinct `Registry` members",
        "unsanctioned `Environment` privates",
        "accesses to those privates",
    )

    @classmethod
    def _inversion_table(cls) -> dict[str, tuple[int, int]]:

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
    WORKFLOW = ROOT / ".github" / "workflows" / "architecture.yml"

    @classmethod
    def setUpClass(cls) -> None:
        cls.yaml = cls.WORKFLOW.read_text(encoding="utf-8")

    def _table_gates(self) -> list[str]:
        section = DOC.split("## Quality gates beyond the boundaries", 1)[1]
        return re.findall(r"^\| `([\w.]+\.py)` \|", section, re.MULTILINE)

    def _workflow_gates(self) -> list[str]:
        found = re.findall(r"python tooling/architecture/([\w.]+\.py)", self.yaml)
        return sorted(set(found))

    def test_table_matches_the_workflow(self) -> None:
        self.assertEqual(set(self._table_gates()), set(self._workflow_gates()))

    def test_the_reproduce_loop_is_exactly_the_contract_gates(self) -> None:

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

        words = NUMBER_WORD_BY_VALUE
        total = len(self._workflow_gates())
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
        self.assertIn(
            f"{words[contract].capitalize()} plus {words[len(ratchets)]} is "
            f"{words[total]}",
            DOC_FLAT,
        )

    def test_the_gates_named_as_check_less_are_exactly_those(self) -> None:
        named = set(self._gates_without_a_check_flag())
        for gate in named:
            self.assertIn(
                f"`{gate.removesuffix('.py')}`",
                DOC,
                f"{gate} implements no --check and the page does not say so",
            )
        sentence = DOC_FLAT.split("are count ratchets", 1)[1].split(
            "implement no `--check` at all", 1
        )[0]
        claimed = {f"{m}.py" for m in re.findall(r"`(\w+)`", sentence)}
        self.assertEqual(claimed, named)

    def test_every_gate_step_is_blocking(self) -> None:
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

    def test_the_digit_form_of_the_checker_count_tracks_the_workflow(self) -> None:

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

        pattern = r"`([\w/]+\.py):(\d+)`"
        self.assertTrue(
            re.findall(pattern, "see `orm/models/base.py:302` for the hook"),
            "the citation regex no longer matches a citation; it has rotted",
        )
        for name, lineno in re.findall(pattern, DOC):
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
    README = ROOT / "odoo" / "http" / "README.md"

    def test_the_pointer_resolves(self) -> None:
        self.assertIn("`odoo/http/README.md`", DOC)
        self.assertTrue(self.README.is_file())
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
    def test_pinned_cycles_are_the_ones_named(self) -> None:

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
        import py_cycle_check

        report = py_cycle_check.check()
        orm = [c for c in report.cycles if any(m.startswith("odoo.orm") for m in c)]
        self.assertEqual(orm, [], "the ORM has a cycle; the page says it has none")
        self.assertIn("**The ORM has none.**", DOC_FLAT)

    def test_removed_module_count_and_names(self) -> None:

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
        readme = (ROOT / "odoo" / "_monkeypatches" / "README.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("| `urllib3.py` |", readme)
        self.assertNotIn("Those names are quoted rather than backticked", DOC_FLAT)


class TestPatchModuleConvention(unittest.TestCase):
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
        self.assertIn("non-underscore submodule exposes `patch_module()`", DOC_FLAT)


class TestEdgeCountConventions(unittest.TestCase):
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
    def test_the_example_does_not_claim_to_be_the_current_floor(self) -> None:

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
        src = (ROOT / "tooling" / "architecture" / "py_function_length.py").read_text(
            encoding="utf-8"
        )
        match = re.search(r"^MAX_LINES = (\d+)$", src, re.MULTILINE)
        self.assertIsNotNone(match, "py_function_length.MAX_LINES is gone")
        self.assertIn(f"*excess lines* over {match.group(1)}", DOC_FLAT)


class TestFilestoreLayout(unittest.TestCase):
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
        src = (ROOT / "odoo" / "libs" / "hashing.py").read_text(encoding="utf-8")
        self.assertIn('ALGO_TAG = "b3" if HAS_BLAKE3 else "s1"', src)
        self.assertIn("depends on an optional dependency", DOC_FLAT)


class TestAddonSuiteFigures(unittest.TestCase):
    @staticmethod
    def _suite(module: str) -> tuple[int, int]:
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

        self.assertIn("Method counts, not line counts.", DOC_FLAT)
        for module in ("test_orm", "test_read_group"):
            _methods, lines = self._suite(module)
            self.assertNotIn(f"{lines:,} lines", DOC_FLAT)

    def test_every_prose_figure_is_fresh(self) -> None:
        """Delegates to the generator that owns these measurements.

        The figures live inside sentences on narrative pages, where a
        ``MEASURED`` stanza would cost the sentence its argument, so
        ``doc_restated_counts.py`` rewrites the digits in place instead.
        Run it with ``--update`` after the change that moved one.
        """
        problems = doc_restated_counts.check()
        self.assertFalse(
            problems,
            "prose figures have drifted from what the tree measures; run "
            "`python tooling/architecture/doc_restated_counts.py --update`:\n  "
            + "\n  ".join(problems),
        )


class TestTheEnforcedClaimIsBounded(unittest.TestCase):
    BOUNDARY = ROOT / ".github" / "workflows" / "architecture.yml"
    INTEGRATION = ROOT / ".github" / "workflows" / "integration_tests.yml"

    def test_the_boundary_job_really_has_no_database(self) -> None:
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
        self.assertIn("OrmCore", DOC)
        self.assertIn('never as "the framework works"', DOC_FLAT)
        core = (ROOT / "odoo" / "orm" / "components" / "core.py").read_text(
            encoding="utf-8"
        )
        self.assertRegex(core, r"_cache\b")
        self.assertRegex(core, r"_engine\b")


class TestPermissionIsNotPractice(unittest.TestCase):
    @property
    def LAYER0(self) -> tuple[str, ...]:

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
        contract = next(
            c for c in layer_check.CONTRACTS if c.name == "orm-layer0-is-foundational"
        )
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
    CONFIG = ROOT / "odoo" / "tools" / "config.py"
    SERVICE = ROOT / "odoo" / "service"

    @staticmethod
    def _literal(node: ast.AST) -> object:
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
        section = DOC.split("## The limits that end a request or a worker", 1)[1]
        section = re.split(r"^## ", section, maxsplit=1, flags=re.MULTILINE)[0]
        rows = re.findall(r"^\| `(\w+)` \| `?([^|`]+?)`? \|", section, re.MULTILINE)
        return {name: value.strip() for name, value in rows}

    def test_the_soft_hard_gap_is_derived(self) -> None:

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
            if stated.endswith("MB"):
                actual //= 1024 * 1024
                stated = stated.removesuffix(" MB")
            stated = stated.removesuffix(" s")
            self.assertEqual(
                str(actual), stated, f"{knob}: page says {stated}, config says {actual}"
            )

    def test_only_the_soft_memory_limit_is_enforced(self) -> None:
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
        self.assertIn(
            "not enforced in-process", self.CONFIG.read_text(encoding="utf-8")
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

    def test_every_scenario_carries_a_date(self) -> None:
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
    @staticmethod
    def _block(heading: str) -> str:
        return DOC.split(heading, 1)[1].split("```", 2)[1]

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
        src = (ROOT / "odoo" / "modules" / "loading.py").read_text(encoding="utf-8")
        body = src.split("\ndef load_modules(", 1)[1]
        return re.findall(r"loader\.(\w+)\(", body)

    def test_registry_build_phases_are_real_and_ordered(self) -> None:
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
        self.assertIn(f"{len(order)} calls", DOC_FLAT, "the full phase count is stated")

    def test_the_reload_reentry_is_real(self) -> None:
        self.assertIn("may force one full reload", DOC)
        src = (ROOT / "odoo" / "modules" / "loading.py").read_text(encoding="utf-8")
        handler = src.split("except _UninstallRequiresReload:", 1)
        self.assertEqual(
            len(handler), 2, "_UninstallRequiresReload is no longer caught"
        )
        self.assertIn("Registry.new(", handler[1].split("\n\n", 1)[0])

    def test_transaction_owns_what_the_sketch_draws(self) -> None:
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
        self.assertIn("is **interned** per `(cr, uid, su, context)`", DOC_FLAT)
        src = (ROOT / "odoo" / "orm" / "runtime" / "environment.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("envs.lookup(envs.key(uid, su, frozen_context))", src)

    def test_flush_loop_names_and_cap(self) -> None:
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
            self.assertIn(name, DOC, f"the flush sketch dropped {name}")
            self.assertRegex(src, re.compile(rf"^    def {name}\b", re.MULTILINE))
        self.assertIn("flush_all()", DOC)
        self.assertRegex(env, re.compile(r"^    def flush_all\b", re.MULTILINE))
        self.assertIn("`tolerant_recompute`", DOC)
        self.assertIn('context.get("tolerant_recompute")', env)
        self.assertIn("cr.pipeline()", DOC)
        self.assertIn("with self.cr.pipeline():", env)


class TestContractNamesResolveEverywhere(unittest.TestCase):
    def test_every_kebab_case_citation_is_a_real_contract(self) -> None:
        known = {c.name for c in layer_check.CONTRACTS}
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
