#!/usr/bin/env python3
"""Self-test for ``mixin_coupling_check.py``.

A gate that measures the wrong thing is worse than no gate: it reports a number
nobody can act on and green-lights the drift it exists to catch. The cases below
pin the three ways this particular checker could lie —

* counting a *local helper* class as a mixin (``traversal.py`` defines a
  ``ReversibleComparator`` with ``__eq__``/``__lt__``/``__hash__``, ``cache.py``
  a ``RecordCache`` with ``__getitem__``/``__iter__``/``__len__``; both collide
  by name with ``IterationMixin`` and would fabricate edges and phantom MRO
  collisions),
* missing declarations inside ``if TYPE_CHECKING:`` (where several mixins state
  their surface, so skipping it would drop real edges), and
* reporting a cycle that is not there, or missing one that is.

Run directly (``python tooling/architecture/test_mixin_coupling_check.py``) or
under pytest.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mixin_coupling_check as mcc


def _units_from_source(**sources: str) -> dict[str, mcc.Unit]:
    """Build units from in-memory source, bypassing the filesystem walk."""
    units: dict[str, mcc.Unit] = {}
    for name, src in sources.items():
        unit = mcc.Unit(name)
        mcc._SelfUseCollector(unit).visit(ast.parse(src))
        units[name] = unit
    return units


class TestClassSelection(unittest.TestCase):
    def test_a_mixin_subclass_counts(self):
        units = _units_from_source(
            a="class AMixin(_ModelStubs):\n    def foo(self): pass\n"
        )
        self.assertEqual(units["a"].defines, {"foo"})

    def test_base_model_counts(self):
        units = _units_from_source(
            b="class BaseModel(X, metaclass=M):\n    def bar(self): pass\n"
        )
        self.assertEqual(units["b"].defines, {"bar"})

    def test_a_local_helper_class_does_not_count(self):
        """The real trap: ``ReversibleComparator`` / ``RecordCache``."""
        units = _units_from_source(
            t="""
class ReversibleComparator:
    def __eq__(self, other): return True
    def __lt__(self, other): return True

class TraversalMixin(_ModelStubs):
    def sorted(self): return self._name
"""
        )
        self.assertEqual(units["t"].defines, {"sorted"})
        self.assertNotIn("__eq__", units["t"].defines)

    def test_self_use_inside_a_helper_class_is_not_attributed_to_the_mixin(self):
        units = _units_from_source(
            t="""
class Helper:
    def go(self): return self.not_a_mixin_member

class TMixin(_ModelStubs):
    def real(self): return self._fields
"""
        )
        self.assertEqual(units["t"].uses, {"_fields"})


class TestTypeCheckingDeclarations(unittest.TestCase):
    def test_names_declared_under_type_checking_are_collected(self):
        units = _units_from_source(
            m="""
class MMixin(_ModelStubs):
    if TYPE_CHECKING:
        def helper(self) -> int: ...
    def use(self): return self.helper()
"""
        )
        self.assertIn("helper", units["m"].defines)


class TestEdges(unittest.TestCase):
    def test_an_edge_is_created_by_a_self_call_across_units(self):
        units = _units_from_source(
            a="class AMixin(_ModelStubs):\n    def go(self): return self.target\n",
            b="class BMixin(_ModelStubs):\n    def target(self): pass\n",
        )
        edges, collisions = mcc.build_edges(units)
        self.assertEqual(edges["a"]["b"], {"target"})
        self.assertEqual(collisions, {})

    def test_a_self_call_within_one_unit_creates_no_edge(self):
        units = _units_from_source(
            a="class AMixin(_ModelStubs):\n    def go(self): return self.own\n    def own(self): pass\n"
        )
        edges, _ = mcc.build_edges(units)
        self.assertEqual(dict(edges.get("a", {})), {})

    def test_a_name_defined_twice_is_reported_as_a_collision(self):
        units = _units_from_source(
            a="class AMixin(_ModelStubs):\n    def dup(self): pass\n",
            b="class BMixin(_ModelStubs):\n    def dup(self): pass\n",
        )
        _, collisions = mcc.build_edges(units)
        self.assertEqual(collisions.get("dup"), {"a", "b"})

    def test_slots_is_not_a_collision(self):
        units = _units_from_source(
            a="class AMixin(_ModelStubs):\n    __slots__ = ()\n",
            b="class BMixin(_ModelStubs):\n    __slots__ = ()\n",
        )
        _, collisions = mcc.build_edges(units)
        self.assertEqual(collisions, {})


class TestScc(unittest.TestCase):
    def test_a_dag_has_no_cycle(self):
        edges = {"a": {"b": {"x"}}, "b": {"c": {"y"}}}
        found = [
            c for c in mcc.strongly_connected({"a", "b", "c"}, edges) if len(c) > 1
        ]
        self.assertEqual(found, [])

    def test_a_two_cycle_is_found(self):
        edges = {"a": {"b": {"x"}}, "b": {"a": {"y"}}}
        found = [c for c in mcc.strongly_connected({"a", "b"}, edges) if len(c) > 1]
        self.assertEqual(found, [["a", "b"]])

    def test_a_three_cycle_is_found(self):
        edges = {"a": {"b": {"x"}}, "b": {"c": {"y"}}, "c": {"a": {"z"}}}
        found = [
            c for c in mcc.strongly_connected({"a", "b", "c"}, edges) if len(c) > 1
        ]
        self.assertEqual(found, [["a", "b", "c"]])

    def test_excluding_a_node_can_break_a_cycle(self):
        """The ``scc_without_base`` metric depends on exactly this."""
        edges = {"a": {"hub": {"x"}}, "hub": {"b": {"y"}}, "b": {"hub": {"z"}}}
        nodes = {"a", "b", "hub"}
        with_hub = [c for c in mcc.strongly_connected(nodes, edges) if len(c) > 1]
        without = [
            c for c in mcc.strongly_connected(nodes - {"hub"}, edges) if len(c) > 1
        ]
        self.assertEqual(with_hub, [["b", "hub"]])
        self.assertEqual(without, [])


class TestRealTree(unittest.TestCase):
    """The checker must produce a usable answer on the actual model package."""

    @classmethod
    def setUpClass(cls):
        cls.m = mcc.measure()

    def test_it_found_the_mixins(self):
        self.assertIn("base.py", self.m["units"])
        for expected in ("create", "write", "search", "read", "read_group/mixin"):
            self.assertIn(expected, self.m["units"])

    def test_the_read_group_subpackage_is_four_units_not_one(self):
        """Collapsing it to one hid 10 edges and a 3-cycle; see ``_unit_name``."""
        for part in ("mixin", "sql", "format", "fill"):
            self.assertIn(f"read_group/{part}", self.m["units"])

    def test_every_unit_participates(self):
        """A unit with no defines and no uses would be a measurement artefact."""
        for name, unit in self.m["_units"].items():
            self.assertTrue(unit.defines or unit.uses, f"{name} is an isolated node")

    def test_there_are_no_cross_unit_name_collisions(self):
        self.assertEqual(
            self.m["collisions"],
            {},
            "two mixins define the same name; which one wins depends only on the "
            "order of the bases in `class BaseModel(...)`",
        )

    def test_the_measured_numbers_are_within_baseline(self):
        self.assertEqual(mcc.main(["--check"]), 0)


class TestAgreesWithTheRuntimeMro(unittest.TestCase):
    """The AST model must match what Python actually composes.

    This is the check that caught the original version's real error: it treated
    the ``read_group`` *subpackage* as one unit, but ``BaseModel.__mro__``
    contains four separate classes from it (``ReadGroupMixin``,
    ``_ReadGroupSQLMixin``, ``_ReadGroupFormatMixin``, ``_ReadGroupFillMixin``).
    That collapse misattributed 14 names and hid 10 edges and an entire 3-cycle.

    An AST tool agreeing with itself proves nothing; importing the real class and
    comparing is the only independent oracle available. Skipped rather than
    failed when ``odoo`` cannot be imported, so the gate's own suite stays
    runnable in a bare checkout.
    """

    @classmethod
    def setUpClass(cls):
        try:
            sys.path.insert(0, str(mcc.ROOT))
            from odoo.orm.models.base import BaseModel
        except Exception as exc:  # pragma: no cover - environment dependent
            raise unittest.SkipTest(f"odoo not importable: {exc}") from exc
        cls.mro = BaseModel.__mro__
        cls.units = mcc.collect_units()

    @staticmethod
    def _unit_of(cls_) -> str | None:
        mod = cls_.__module__
        prefix = "odoo.orm.models.mixins."
        if mod == "odoo.orm.models.base":
            return mcc.BASE_UNIT
        if mod.startswith(prefix):
            return prefix and mod[len(prefix) :].replace(".", "/")
        return None

    def test_every_composed_class_maps_to_exactly_one_unit(self):
        runtime = {
            u
            for c in self.mro
            if (u := self._unit_of(c)) and u.split("/")[-1] not in mcc.EXCLUDED_UNITS
        }
        self.assertEqual(
            runtime - set(self.units),
            set(),
            "a class in BaseModel.__mro__ has no corresponding unit",
        )
        self.assertEqual(
            set(self.units) - runtime,
            set(),
            "a unit corresponds to no class in BaseModel.__mro__",
        )

    def test_ast_ownership_matches_the_runtime_defining_class(self):
        owner: dict[str, str] = {}
        for name, unit in self.units.items():
            for member in unit.defines:
                owner.setdefault(member, name)

        mismatches = []
        for member, ast_unit in sorted(owner.items()):
            definer = next((c for c in self.mro if member in c.__dict__), None)
            if definer is None:
                continue
            runtime_unit = self._unit_of(definer)
            if runtime_unit is None or runtime_unit in mcc.EXCLUDED_UNITS:
                continue
            if runtime_unit != ast_unit:
                mismatches.append(f"{member}: ast={ast_unit} runtime={runtime_unit}")
        self.assertEqual(mismatches, [], "AST ownership disagrees with the MRO")

    def test_the_mixins_really_are_stateless(self):
        """``__slots__ = ()`` everywhere is what makes the composition free."""
        missing = [
            f"{c.__module__}.{c.__name__}"
            for c in self.mro
            if self._unit_of(c) and "__slots__" not in c.__dict__
        ]
        self.assertEqual(missing, [])


class TestRatchetDirection(unittest.TestCase):
    """Both directions must fail: growth is drift, and so is an unrecorded win."""

    @staticmethod
    def _at_baseline(**overrides):
        m = {
            "max_scc": mcc.BASELINE["max_scc"],
            "cyclic_edges": mcc.BASELINE["cyclic_edges"],
            "scc_without_base": mcc.BASELINE["scc_without_base"],
        }
        m.update(overrides)
        return {k: s for k, _, _, s in mcc._verdicts(m)}

    def test_a_clean_tree_is_ok(self):
        self.assertEqual(set(self._at_baseline().values()), {"ok"})

    def test_growth_fails(self):
        for metric in ("max_scc", "cyclic_edges", "scc_without_base"):
            with self.subTest(metric=metric):
                got = self._at_baseline(**{metric: mcc.BASELINE[metric] + 1})
                self.assertEqual(got[metric], "GREW")

    def test_an_unrecorded_improvement_fails(self):
        for metric in ("max_scc", "cyclic_edges", "scc_without_base"):
            with self.subTest(metric=metric):
                got = self._at_baseline(**{metric: mcc.BASELINE[metric] - 1})
                self.assertEqual(got[metric], "IMPROVED")


class TestCyclicEdges(unittest.TestCase):
    """``cyclic_edges``, not the raw edge count, is the tangling measure.

    The raw count was ratcheted first and the first real refactor disproved it:
    extracting a method onto a new leaf deleted a 3-cycle and *raised* ``edges``
    85 -> 87, because a new unit brings its own edges. These pin the property
    that made the replacement necessary.
    """

    def test_a_dag_has_no_cyclic_edges(self):
        units = _units_from_source(
            a="class AMixin(_ModelStubs):\n    def go(self): return self.t\n",
            b="class BMixin(_ModelStubs):\n    def t(self): pass\n",
        )
        edges, _ = mcc.build_edges(units)
        sccs = [c for c in mcc.strongly_connected(set(units), edges) if len(c) > 1]
        self.assertEqual(sccs, [])

    def test_splitting_a_unit_out_does_not_raise_tangling(self):
        """Before: a<->b cycle. After: the shared member moves to a leaf."""
        before = _units_from_source(
            a="class AMixin(_ModelStubs):\n    def go(self): return self.t\n    def shared(self): pass\n",
            b="class BMixin(_ModelStubs):\n    def t(self): return self.shared\n",
        )
        after = _units_from_source(
            a="class AMixin(_ModelStubs):\n    def go(self): return self.t\n",
            b="class BMixin(_ModelStubs):\n    def t(self): return self.shared\n",
            leaf="class LMixin(_ModelStubs):\n    def shared(self): pass\n",
        )

        def tangling(units):
            edges, _ = mcc.build_edges(units)
            sccs = [c for c in mcc.strongly_connected(set(units), edges) if len(c) > 1]
            comp = {u: i for i, c in enumerate(sccs) for u in c}
            return (
                sum(
                    1
                    for s, ts in edges.items()
                    for d in ts
                    if comp.get(s, -1) == comp.get(d, -2)
                ),
                sum(len(t) for t in edges.values()),
            )

        cyc_before, raw_before = tangling(before)
        cyc_after, raw_after = tangling(after)
        self.assertEqual(cyc_before, 2, "a <-> b is two cyclic edges")
        self.assertEqual(cyc_after, 0, "extraction must remove the cycle")
        self.assertGreaterEqual(
            raw_after, raw_before, "raw edges do not fall -- that is the whole point"
        )


class TestFieldComposition(unittest.TestCase):
    """The gate was hard-coded to ``BaseModel``; ``Field`` is built the same way.

    ``Field(_FieldDescriptionMixin, _FieldConvertMixin, _FieldSqlMixin)`` over a
    ``_FieldStubs`` typing declaration is the same construction, and was measured
    by nothing while being 1401 lines against 628 in its three mixins -- the
    inverse of the ratio ``models/`` reached.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.comp = mcc.FIELD_COMPOSITION
        cls.units = mcc.collect_units(cls.comp)
        cls.m = mcc.measure(comp=cls.comp)

    def test_it_collects_the_mixin_composition_and_nothing_else(self):
        self.assertEqual(
            {
                "base.py",
                "_field_convert",
                "_field_description",
                "_field_metadata",
                "_field_sql",
            },
            set(self.units),
        )

    def test_concrete_field_types_are_not_units(self):
        """``textual``/``numeric``/``relational`` are subclasses, not mixins.

        They override base methods freely -- ``BaseString`` overrides six of
        ``Field``'s twelve cache methods -- but that is the *override* surface,
        a different question from mixin composition. Including them would
        conflate the two graphs.
        """
        for name in ("textual", "numeric", "binary", "relational/many2many"):
            self.assertNotIn(name, self.units)

    def test_the_stub_module_is_excluded(self):
        self.assertNotIn("_field_stubs", self.units)

    def test_the_composition_is_a_dag(self):
        """It was not when this gate first ran.

        The first run found ``_field_convert`` <-> ``base.py``. These
        assertions named both endpoints so that fixing it would be a visible
        diff here rather than a silent baseline edit -- and it was: they failed
        the moment the cycle went, which is what turned them into these.
        """
        self.assertEqual([], self.m["sccs"])
        self.assertEqual(0, self.m["cyclic_edges"])
        self.assertEqual(0, mcc.FIELD_BASELINE["cyclic_edges"])

    def test_the_metadata_leaf_is_a_leaf(self):
        """The property that broke the cycle, and the one that can silently rot.

        ``base.py`` still reaches conversion from the descriptor protocol --
        that edge is fine, one direction is a DAG edge. What must not come back
        is conversion reaching the root: it now asks ``_field_metadata`` what a
        field *is*, and that unit reaches nothing, so nothing that uses it can
        close a cycle through it.
        """
        edges, _ = mcc.build_edges(self.units)
        self.assertLessEqual(
            {"convert_to_cache", "convert_to_record", "convert_to_write"},
            edges["base.py"]["_field_convert"],
        )
        self.assertNotIn(
            "base.py",
            edges.get("_field_convert", {}),
            "conversion reaches the composition root again -- that is the "
            "back-edge _FieldMetadataMixin was extracted to remove",
        )
        self.assertLessEqual(
            {"column_type", "company_dependent", "translate"},
            edges["_field_convert"]["_field_metadata"],
        )
        self.assertEqual(
            {}, edges.get("_field_metadata", {}), "_field_metadata must stay a leaf"
        )

    def test_it_has_its_own_floors(self):
        """Two graphs, two baselines -- neither may mask the other."""
        self.assertIsNot(mcc.FIELD_BASELINE, mcc.BASELINE)
        self.assertEqual(
            {
                "max_scc",
                "cyclic_edges",
                "scc_without_base",
                "unowned_shared_state",
            },
            set(mcc.FIELD_BASELINE),
        )

    def test_the_recordset_view_is_off_for_fields(self):
        """``RECORDSET_PRODUCERS`` are BaseModel methods; a Field holds no
        recordset of itself, so the wide view would just duplicate the narrow
        one and double the ratchet noise."""
        self.assertFalse(self.comp.recordset_aware)
        self.assertTrue(mcc.MODEL_COMPOSITION.recordset_aware)

    def test_the_model_composition_is_unchanged_by_the_generalisation(self):
        """The refactor must not move the graph it was already measuring."""
        model = mcc.measure()
        self.assertEqual(mcc.BASELINE["max_scc"], model["max_scc"])
        self.assertEqual(mcc.BASELINE["cyclic_edges"], model["cyclic_edges"])
        self.assertEqual(31, len(model["units"]))


class TestRegistryComposition(unittest.TestCase):
    """``Registry`` is the third class built this way, and was the tangled one.

    ``Registry(_RegistryFieldsMixin, _RegistrySchemaMixin, ...)`` over a
    ``_RegistryStubs`` typing declaration is the same construction as
    ``BaseModel``/``_ModelStubs`` and ``Field``/``_FieldStubs``. It was measured
    by nothing until 2026-08-09, and the first run found a **3-unit cycle over 4
    edges** -- the only one of the three compositions that was not a DAG.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.comp = mcc.REGISTRY_COMPOSITION
        cls.units = mcc.collect_units(cls.comp)
        cls.m = mcc.measure(comp=cls.comp)

    def test_it_collects_the_mixin_composition_and_nothing_else(self):
        """``environment``/``transaction``/``backend`` are collaborators.

        They live in the same flat package and contribute no composed class, so
        the unit set stays the registry's own fragments.
        """
        self.assertEqual(
            {
                "registry.py",
                "_registry_fields",
                "_registry_schema",
                "_registry_models",
                "_registry_init_phase",
                "_registry_capabilities",
            },
            set(self.units),
        )

    def test_the_composition_is_a_dag(self):
        """The property the two leaves were extracted to buy.

        Not "the tangle must not grow" -- there must be no tangle at all, the
        same bar the other two compositions are held to.
        """
        self.assertEqual(0, self.m["cyclic_edges"])
        self.assertEqual(1, self.m["max_scc"])
        self.assertEqual([], self.m["sccs"])

    def test_the_leaves_have_no_out_edge_into_the_composition(self):
        """What makes the DAG hold, stated as the rule rather than the result.

        ``_registry_models`` and ``_registry_init_phase`` exist to be depended
        on. A leaf that reaches nothing back cannot close a cycle -- the design
        rule under *Coupling the import graph cannot see* in
        ``doc/architecture/module.md``. If either grows an out-edge, the cycle
        can come back even while ``cyclic_edges`` is briefly still 0.
        """
        edges = self.m["_edges"]
        for leaf in (
            "_registry_models",
            "_registry_init_phase",
            "_registry_capabilities",
        ):
            self.assertEqual(
                {},
                edges.get(leaf, {}),
                f"{leaf} must stay a leaf of the Registry composition",
            )

    def test_the_two_mixins_reach_the_leaves_and_not_the_root(self):
        """The back-edges that formed the original cycle, asserted gone.

        ``_registry_fields`` and ``_registry_schema`` reached ``registry.py``
        for ``models`` (and ``init_phase``); both now land on a leaf.
        """
        edges = self.m["_edges"]
        for mixin in ("_registry_fields", "_registry_schema"):
            self.assertNotIn(
                self.comp.root_file,
                edges.get(mixin, {}),
                f"{mixin} reaches the composition root again -- that is the "
                f"edge the leaves were extracted to remove",
            )

    def test_it_has_its_own_floors(self):
        """Three graphs, three baselines -- none may mask another."""
        self.assertIsNot(mcc.REGISTRY_BASELINE, mcc.BASELINE)
        self.assertIsNot(mcc.REGISTRY_BASELINE, mcc.FIELD_BASELINE)
        self.assertEqual(
            {
                "max_scc",
                "cyclic_edges",
                "scc_without_base",
                "unowned_shared_state",
            },
            set(mcc.REGISTRY_BASELINE),
        )


class TestUnownedSharedState(unittest.TestCase):
    """The metric that says how much ``cyclic_edges`` cannot see.

    Written after ``cyclic_edges`` 0 was claimed for ``Registry`` and turned out
    to be a claim about *declared* ownership only. Two properties matter: it
    must find state nobody declares, and it must rise exactly when someone
    silences an edge by deleting a declaration.
    """

    def test_state_read_by_two_units_and_declared_by_none_is_reported(self):
        units = _units_from_source(
            a="class AMixin(_ModelStubs):\n    def go(self): return self.shared\n",
            b="class BMixin(_ModelStubs):\n    def go2(self): return self.shared\n",
        )
        self.assertEqual({"shared": ["a", "b"]}, mcc.unowned_from_units(units))

    def test_state_declared_by_a_unit_is_an_edge_instead(self):
        """Give it an owner and it leaves this count for the graph."""
        units = _units_from_source(
            a="class AMixin(_ModelStubs):\n    def go(self): return self.shared\n",
            b="class BMixin(_ModelStubs):\n    shared: dict\n    def go2(self): return self.shared\n",
        )
        self.assertEqual({}, mcc.unowned_from_units(units))
        edges, _ = mcc.build_edges(units)
        self.assertEqual({"shared"}, edges["a"]["b"])

    def test_read_by_only_one_unit_is_not_shared_state(self):
        units = _units_from_source(
            a="class AMixin(_ModelStubs):\n    def go(self): return self.private_thing\n",
            b="class BMixin(_ModelStubs):\n    def other(self): return 1\n",
        )
        self.assertEqual({}, mcc.unowned_from_units(units))

    def test_dunders_are_not_counted(self):
        units = _units_from_source(
            a="class AMixin(_ModelStubs):\n    def go(self): return self.__dict__\n",
            b="class BMixin(_ModelStubs):\n    def go2(self): return self.__dict__\n",
        )
        self.assertEqual({}, mcc.unowned_from_units(units))

    def test_deleting_a_declaration_moves_this_count_up_as_it_moves_edges_down(self):
        """The gaming vector, demonstrated end to end.

        Deleting a class-body declaration removes a measured edge without
        changing behaviour — that is how ``Registry``'s ``cyclic_edges`` could
        be taken from 4 to 2 on the pre-split tree. The two numbers must move in
        opposite directions so the pair cannot be improved by hiding.
        """
        declared = _units_from_source(
            a="class AMixin(_ModelStubs):\n    def go(self): return self.shared\n",
            b="class BMixin(_ModelStubs):\n    shared: dict\n    def go2(self): return self.shared\n",
        )
        silenced = _units_from_source(
            a="class AMixin(_ModelStubs):\n    def go(self): return self.shared\n",
            b="class BMixin(_ModelStubs):\n    def go2(self): return self.shared\n",
        )
        edges_declared, _ = mcc.build_edges(declared)
        edges_silenced, _ = mcc.build_edges(silenced)

        self.assertEqual(1, sum(len(t) for t in edges_declared.values()))
        self.assertEqual(0, sum(len(t) for t in edges_silenced.values()))
        self.assertEqual(0, len(mcc.unowned_from_units(declared)))
        self.assertEqual(1, len(mcc.unowned_from_units(silenced)))

    def test_every_composition_ratchets_it(self):
        """A number reported but not ratcheted would not stop the regression."""
        for comp in mcc.COMPOSITIONS:
            self.assertIn("unowned_shared_state", comp.baseline)
            self.assertEqual(
                len(mcc.unowned_shared_state(comp)),
                comp.baseline["unowned_shared_state"],
                f"{comp.label}'s unowned shared state drifted from its floor",
            )

    def test_the_registry_composition_has_none_left(self):
        """The eight that qualified ``cyclic_edges`` 0 all have owners now.

        ``_constraint_queue``, ``_ordinary_tables``, ``field_setup_dependents``,
        ``has_trigram``, ``has_unaccent``, ``model_graph``, ``not_null_fields``
        and ``unaccent`` were declared in ``_RegistryStubs`` and assigned in
        ``Registry.init``. Each is now declared *and* initialised by the mixin
        whose concern it is, which is what makes this composition a DAG under
        assignment-site ownership as well as under this gate's model.
        """
        self.assertEqual({}, mcc.unowned_shared_state(mcc.REGISTRY_COMPOSITION))

    def test_each_registry_mixin_initialises_its_own_state(self):
        """The mechanism behind the 0, asserted rather than assumed.

        A declaration alone would satisfy this gate while ``Registry.init`` kept
        assigning the member — the exact half-measure the first round shipped.
        """
        runtime = mcc.ROOT / "odoo" / "orm" / "runtime"
        for module, hook in (
            ("_registry_models", "_init_models_container"),
            ("_registry_init_phase", "_init_phase_state"),
            ("_registry_fields", "_init_field_state"),
            ("_registry_schema", "_init_schema_state"),
            ("_registry_capabilities", "_probe_capabilities"),
        ):
            src = (runtime / f"{module}.py").read_text(encoding="utf-8")
            self.assertIn(f"def {hook}(", src, f"{module} lost its init hook")
            self.assertIn(
                f"self.{hook}("
                if hook != "_probe_capabilities"
                else "_probe_capabilities(",
                (runtime / "registry.py").read_text(encoding="utf-8"),
                f"Registry.init no longer calls {hook}",
            )


class TestEveryOrmCompositionIsMeasured(unittest.TestCase):
    """The gate has been blind twice; this is what stops a third time.

    ``Field`` went unmeasured until 2026-08-08, ``Registry`` and ``Cursor``
    until 2026-08-09, and **each turned out to be the worst of the set when
    first measured** -- a 2-cycle, a 3-cycle and a 2-cycle respectively. Every
    one was found by someone noticing the construction by eye, which is not a
    gate.

    So discover composition roots from the tree instead of trusting
    :data:`COMPOSITIONS` to be complete: a class in the **core** with two or
    more ``*Mixin`` bases is one, unless its own name ends in ``Mixin``, in
    which case it is a *unit* of an outer composition (``ReadGroupMixin`` is
    three mixins wide and is measured as one unit of ``BaseModel``).

    The scope was ``odoo/orm`` when this test was written, which would have
    reported clean while ``Cursor`` sat unmeasured in ``odoo/db`` with a cycle
    in it. A coverage test narrower than the thing it guards reproduces the bug
    it exists to catch -- the same lesson ``tooling/test_repo_root`` records.
    """

    @staticmethod
    def _composition_roots() -> dict[str, Path]:
        roots: dict[str, Path] = {}
        core = mcc.ROOT / "odoo"
        for path in sorted(core.rglob("*.py")):
            if "tests" in path.parts or "addons" in path.parts:
                continue
            if "__pycache__" in path.parts or "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef) or node.name.endswith("Mixin"):
                    continue
                mixin_bases = [
                    b.id
                    for b in node.bases
                    if isinstance(b, ast.Name) and b.id.endswith("Mixin")
                ]
                if len(mixin_bases) >= 2:
                    roots[node.name] = path
        return roots

    def test_the_discovered_roots_are_the_five_we_know(self):
        """Pins the discovery itself, so the coverage test below cannot pass
        vacuously by finding nothing."""
        self.assertEqual(
            {"BaseModel", "Field", "Registry", "Request", "Cursor"},
            set(self._composition_roots()),
        )

    def test_every_discovered_root_is_in_COMPOSITIONS(self):
        measured = {c.root_class for c in mcc.COMPOSITIONS}
        missing = {
            name: str(path.relative_to(mcc.ROOT))
            for name, path in self._composition_roots().items()
            if name not in measured
        }
        self.assertFalse(
            missing,
            f"class(es) in the core are built as a mixin composition but are "
            f"measured by no entry in COMPOSITIONS, so a cycle among their "
            f"mixins would move no gate: {missing}",
        )

    def test_every_composition_carries_a_distinct_baseline(self):
        """A shared baseline object would let one graph's floor mask another's."""
        baselines = [id(c.baseline) for c in mcc.COMPOSITIONS]
        self.assertEqual(len(baselines), len(set(baselines)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
