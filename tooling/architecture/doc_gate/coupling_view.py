from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

import layer_check

from ._shared import (
    DOC,
    DOC_FLAT,
    NUMBER_WORDS,
    ROOT,
    _class_bases,
    _imported_modules,
)


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

    def test_the_private_mixins_are_named_correctly(self) -> None:
        private = sorted(base for base in self.bases if base.startswith("_"))
        listing = re.search(r"plus \d+ private\s*\(([^)]*)\)", DOC_FLAT)
        self.assertIsNotNone(listing, "the private-mixin list is no longer on the page")
        named = sorted(set(re.findall(r"`(_\w+Mixin)`", listing.group(1))))
        self.assertTrue(named, "the page names no private mixin; the regex rotted")
        self.assertEqual(
            private,
            named,
            f"the page's private-mixin list and BaseModel's bases disagree — "
            f"on the page and not a base: {sorted(set(named) - set(private))}; "
            f"a base and not on the page: {sorted(set(private) - set(named))}",
        )

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

        metrics = mcc.metadata_metrics()
        units = mcc.collect_units()
        self.assertEqual(metrics["units"], len(units))

        readers = {
            attr: sum(
                attr in unit.uses for name, unit in units.items() if name != "_metadata"
            )
            for attr in mcc.METADATA_ATTRS
        }
        stated = {
            attr: metrics[f"{attr.lstrip('_')}_readers"] for attr in mcc.METADATA_ATTRS
        }
        self.assertEqual(stated, readers)

        self.assertEqual(
            mcc.doc_measured.check(mcc.METADATA_MODULE, metrics),
            [],
            "mixins/_metadata.py MEASURED block is stale; run "
            "mixin_coupling_check.py --update-doc",
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
        # Registry accesses were Layer-1-heavy only while the collector matched
        # a spelling: it followed `<expr>.pool` and a name spelled `pool`, so a
        # registry held under any other name went uncounted.  Teaching it to
        # follow a local bound from a pool expression levelled the two, and the
        # conclusion moved from volume to kind with it.
        self.assertGreaterEqual(*measured["`Registry` accesses"][::-1])
        self.assertGreater(*measured["unsanctioned `Environment` privates"])
        layer1, layer2 = measured["distinct `Registry` members"]
        self.assertGreater(
            layer2, layer1, "Layer 2 is no longer the wider consumer by member"
        )
        self.assertIn(
            "The inversion is one of kind, not of volume: the two reach the "
            "Registry about as often, and Layer 2 reaches more *distinct* "
            "members",
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
