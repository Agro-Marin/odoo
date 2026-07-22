"""Pure-Python tests for ModelGraph and TriggerTree — no Odoo, no database.

Uses a lightweight MockField class as hashable mock field keys with the
attributes that the graph's internal helpers check.
"""

import unittest

from odoo.orm.components.model_graph import (
    ModelGraph,
    TriggerTree,
    _Collector,
    _concat_paths,
)

# ---------------------------------------------------------------------------
# Helpers — mock field factories
# ---------------------------------------------------------------------------


class MockField:
    """Hashable mock field object for testing ModelGraph."""

    __slots__ = (
        "comodel_name",
        "compute",
        "inverse_name",
        "is_stored_computed",
        "model_name",
        "name",
        "relational",
        "store",
        "type",
    )

    def __init__(
        self,
        name: str,
        model_name: str = "m",
        type_: str = "char",
        relational: bool = False,
        **kw,
    ) -> None:
        self.name = name
        self.model_name = model_name
        self.type = type_
        self.relational = relational
        self.comodel_name = kw.get("comodel_name")
        self.inverse_name = kw.get("inverse_name")
        self.is_stored_computed = kw.get("is_stored_computed", False)
        self.compute = kw.get("compute")
        self.store = kw.get("store", False)

    def __repr__(self) -> str:
        return f"MockField({self.name!r})"

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, other: object) -> bool:
        return self is other


def _field(name, model="m", type_="char", relational=False, **kw):
    """Create a mock field with the attributes ModelGraph needs."""
    return MockField(name, model, type_, relational, **kw)


# ---------------------------------------------------------------------------
# TriggerTree tests
# ---------------------------------------------------------------------------


class TestTriggerTree(unittest.TestCase):
    """Test TriggerTree data structure operations."""

    def test_empty_tree_is_falsy(self) -> None:
        tree = TriggerTree()
        self.assertFalse(tree)

    def test_tree_with_root_is_truthy(self) -> None:
        tree = TriggerTree(["field_a"])
        self.assertTrue(tree)

    def test_tree_with_children_is_truthy(self) -> None:
        tree = TriggerTree()
        tree["edge"] = TriggerTree(["field_b"])
        self.assertTrue(tree)

    def test_increase_creates_subtree(self) -> None:
        tree = TriggerTree()
        sub = tree.increase("edge_x")
        self.assertIsInstance(sub, TriggerTree)
        self.assertIs(tree["edge_x"], sub)

    def test_increase_returns_existing(self) -> None:
        tree = TriggerTree()
        sub1 = tree.increase("edge_x")
        sub2 = tree.increase("edge_x")
        self.assertIs(sub1, sub2)

    def test_depth_first(self) -> None:
        root = TriggerTree(["A"])
        child = TriggerTree(["B"])
        grandchild = TriggerTree(["C"])
        child["gc"] = grandchild
        root["ch"] = child

        nodes = list(root.depth_first())
        self.assertEqual(len(nodes), 3)
        self.assertIs(nodes[0], root)
        self.assertIs(nodes[1], child)
        self.assertIs(nodes[2], grandchild)

    def test_repr(self) -> None:
        tree = TriggerTree(["f1"])
        r = repr(tree)
        self.assertIn("TriggerTree", r)
        self.assertIn("f1", r)

    # -- merge --

    def test_merge_empty(self) -> None:
        result = TriggerTree.merge([])
        self.assertFalse(result)

    def test_merge_single(self) -> None:
        tree = TriggerTree(["A", "B"])
        result = TriggerTree.merge([tree])
        self.assertEqual(list(result.root), ["A", "B"])

    def test_root_is_immutable_tuple(self) -> None:
        """``root`` is a tuple: the single-tree merge fast path returns the
        shared cached node by identity, so a mutable root would let one consumer
        corrupt the registry-wide trigger cache.
        """
        tree = TriggerTree(["A", "B"])
        self.assertIsInstance(tree.root, tuple)
        # merge fast path aliases the cached node; mutation must be impossible
        self.assertIs(TriggerTree.merge([tree]), tree)
        with self.assertRaises(AttributeError):
            tree.root.append("C")  # type: ignore[attr-defined]

    def test_merge_roots(self) -> None:
        t1 = TriggerTree(["A", "B"])
        t2 = TriggerTree(["B", "C"])
        result = TriggerTree.merge([t1, t2])
        # A, B, C — B deduplicated
        self.assertEqual(list(result.root), ["A", "B", "C"])

    def test_merge_subtrees(self) -> None:
        edge = "edge_x"
        t1 = TriggerTree()
        t1[edge] = TriggerTree(["H1"])
        t2 = TriggerTree()
        t2[edge] = TriggerTree(["H2"])

        result = TriggerTree.merge([t1, t2])
        self.assertIn(edge, result)
        self.assertEqual(list(result[edge].root), ["H1", "H2"])

    def test_merge_select_filter(self) -> None:
        """The select function filters root fields."""
        t1 = TriggerTree(["keep", "drop"])
        result = TriggerTree.merge([t1], select=lambda f: f == "keep")
        self.assertEqual(list(result.root), ["keep"])

    def test_merge_discards_empty_subtrees(self) -> None:
        """Subtrees that become empty after filtering are excluded."""
        edge = "edge_x"
        t1 = TriggerTree()
        t1[edge] = TriggerTree(["only_field"])

        result = TriggerTree.merge([t1], select=lambda f: False)
        self.assertNotIn(edge, result)
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# ModelGraph construction tests
# ---------------------------------------------------------------------------


class TestModelGraphConstruction(unittest.TestCase):
    """Test building a ModelGraph from scratch."""

    def test_add_trigger(self) -> None:
        g = ModelGraph()
        f = _field("price")
        t = _field("total", is_stored_computed=True)
        g.add_trigger(f, (), [t])
        self.assertTrue(g.has_triggers(f))

    def test_add_trigger_deduplicates(self) -> None:
        g = ModelGraph()
        f = _field("price")
        t = _field("total")
        g.add_trigger(f, (), [t])
        g.add_trigger(f, (), [t])
        self.assertEqual(len(g._triggers[f][()]), 1)

    def test_inverses_via_collector(self) -> None:
        g = ModelGraph()
        f = _field("partner_id")
        inv = _field("order_ids")
        g._inverses[f] = (inv,)
        self.assertEqual(g.field_inverses[f], (inv,))

    def test_depends_via_collector(self) -> None:
        g = ModelGraph()
        f = _field("total")
        dep = _field("price")
        g._depends[f] = (dep,)
        self.assertEqual(g.field_depends[f], (dep,))

    def test_depends_context_via_collector(self) -> None:
        g = ModelGraph()
        f = _field("name")
        g._depends_context[f] = ("lang",)
        self.assertEqual(g.field_depends_context[f], ("lang",))

    def test_computed_direct_assignment(self) -> None:
        g = ModelGraph()
        f1 = _field("total")
        f2 = _field("tax")
        g._computed[f1] = [f1, f2]
        g._computed[f2] = [f1, f2]
        self.assertEqual(g.field_computed[f1], [f1, f2])

    def test_reset_field_metadata_clears_in_place(self) -> None:
        # reset_field_metadata clears the collections IN PLACE (preserving
        # object identity) rather than rebinding fresh objects, so live
        # references survive the rebuild — notably
        # Environment._field_depends_context, which caches
        # model_graph._depends_context on the hot Field._get_cache path.
        g = ModelGraph()
        f = _field("price")
        g._depends[f] = ("dep",)
        g._depends_context[f] = ("lang",)
        g._inverses[f] = ("inv",)
        g._computed[f] = ["f1"]
        depends, depends_ctx = g._depends, g._depends_context
        inverses, computed = g._inverses, g._computed

        g.reset_field_metadata()

        # emptied
        self.assertEqual(len(g._depends), 0)
        self.assertEqual(len(g._depends_context), 0)
        self.assertEqual(len(g._inverses), 0)
        self.assertEqual(len(g._computed), 0)
        # same objects (cleared in place, not rebound) — this is what keeps a
        # cached env._field_depends_context reference valid across the reset.
        self.assertIs(g._depends, depends)
        self.assertIs(g._depends_context, depends_ctx)
        self.assertIs(g._inverses, inverses)
        self.assertIs(g._computed, computed)
        self.assertIsInstance(g._depends, _Collector)

    def test_no_triggers_is_falsy(self) -> None:
        g = ModelGraph()
        self.assertFalse(g.has_triggers(_field("whatever")))

    def test_reset_triggers(self) -> None:
        """reset_triggers() clears all trigger data and caches."""
        g = ModelGraph()
        f = _field("price")
        t = _field("total")
        g.add_trigger(f, (), [t])
        g.get_field_trigger_tree(f)  # populate cache
        self.assertTrue(g.has_triggers(f))
        self.assertTrue(g._trigger_trees)

        g.reset_triggers()
        self.assertFalse(g.has_triggers(f))
        self.assertFalse(g._trigger_trees)
        self.assertFalse(g._modifying_relations)

    def test_reset_triggers_allows_rebuild(self) -> None:
        """After reset_triggers(), new triggers can be added incrementally."""
        g = ModelGraph()
        f1 = _field("price")
        t1 = _field("total")
        g.add_trigger(f1, (), [t1])

        # Reset and rebuild with different data
        g.reset_triggers()
        f2 = _field("name")
        t2 = _field("display_name")
        g.add_trigger(f2, (), [t2])

        # Old data gone, new data present
        self.assertFalse(g.has_triggers(f1))
        self.assertTrue(g.has_triggers(f2))
        deps = list(g.get_dependent_fields(f2))
        self.assertIn(t2, deps)

    def test_set_triggers_publishes_atomically(self) -> None:
        """set_triggers() swaps in a prebuilt map and drops derived caches.

        This is the atomic-publish path (Registry._field_triggers builds the map
        locally then hands it over), so the shared graph never holds a partial
        map: the new object becomes visible in a single assignment.
        """
        from collections import defaultdict

        g = ModelGraph()
        f_old, t_old = _field("price"), _field("total")
        g.add_trigger(f_old, (), [t_old])
        g.get_field_trigger_tree(f_old)  # populate derived caches
        self.assertTrue(g._trigger_trees)

        f_new, t_new = _field("name"), _field("display_name")
        staged: defaultdict = defaultdict(lambda: defaultdict(list))
        staged[f_new][()].append(t_new)

        g.set_triggers(staged)
        # The exact prebuilt object is published, and derived caches are dropped.
        self.assertIs(g._triggers, staged)
        self.assertFalse(g._trigger_trees)
        self.assertFalse(g._modifying_relations)
        # The new map is fully queryable; the old one is gone.
        self.assertFalse(g.has_triggers(f_old))
        self.assertTrue(g.has_triggers(f_new))
        self.assertIn(t_new, list(g.get_dependent_fields(f_new)))

    def test_incremental_build_workflow(self) -> None:
        """Simulate the Registry pattern: reset → add_trigger × N → query."""
        g = ModelGraph()
        g.reset_triggers()

        price = _field("price", model="line")
        qty = _field("qty", model="line")
        total = _field("total", model="line", is_stored_computed=True)
        partner_id = _field(
            "partner_id",
            model="line",
            type_="many2one",
            comodel_name="partner",
            relational=True,
        )
        partner_total = _field(
            "partner_total", model="partner", is_stored_computed=True
        )

        # Simulate resolved dependencies:
        # total depends on price (direct) and qty (direct)
        g.add_trigger(price, (), [total])
        g.add_trigger(qty, (), [total])
        # partner_total depends on price via partner_id
        g.add_trigger(price, (partner_id,), [partner_total])

        # Verify trigger tree structure
        tree = g.get_trigger_tree([price])
        self.assertIn(total, tree.root)
        self.assertIn(partner_id, tree)
        self.assertIn(partner_total, tree[partner_id].root)

        tree2 = g.get_trigger_tree([qty])
        self.assertIn(total, tree2.root)

    def test_reset_triggers_preserves_field_metadata(self) -> None:
        """reset_triggers() only clears triggers, not depends/inverses/computed."""
        g = ModelGraph()
        f = _field("price")
        g._depends[f] = ("dep",)
        g._inverses[f] = ("inv",)
        g.add_trigger(f, (), [_field("total")])

        g.reset_triggers()
        # Triggers cleared
        self.assertFalse(g.has_triggers(f))
        # Other metadata preserved
        self.assertEqual(g._depends[f], ("dep",))
        self.assertEqual(g._inverses[f], ("inv",))


# ---------------------------------------------------------------------------
# ModelGraph query tests
# ---------------------------------------------------------------------------


class TestModelGraphQueries(unittest.TestCase):
    """Test querying the dependency graph."""

    def setUp(self) -> None:
        """Build a graph: price → total (direct), partner_id.price → partner_total (via path)."""
        self.g = ModelGraph()

        self.price = _field("price", model="order.line")
        self.total = _field("total", model="order.line", is_stored_computed=True)
        self.partner_id = _field(
            "partner_id",
            model="order.line",
            type_="many2one",
            comodel_name="partner",
            relational=True,
        )
        self.partner_total = _field(
            "partner_total",
            model="partner",
            is_stored_computed=True,
        )

        # price triggers total (direct — empty path)
        self.g.add_trigger(self.price, (), [self.total])
        # price also triggers partner_total (via partner_id path)
        self.g.add_trigger(self.price, (self.partner_id,), [self.partner_total])

    def test_get_trigger_tree_direct(self) -> None:
        tree = self.g.get_trigger_tree([self.price])
        self.assertIn(self.total, tree.root)

    def test_get_trigger_tree_with_path(self) -> None:
        tree = self.g.get_trigger_tree([self.price])
        self.assertIn(self.partner_id, tree)
        subtree = tree[self.partner_id]
        self.assertIn(self.partner_total, subtree.root)

    def test_get_trigger_tree_caches(self) -> None:
        tree1 = self.g.get_field_trigger_tree(self.price)
        tree2 = self.g.get_field_trigger_tree(self.price)
        self.assertIs(tree1, tree2)

    def test_get_trigger_tree_no_triggers(self) -> None:
        tree = self.g.get_trigger_tree([_field("unknown")])
        self.assertFalse(tree)

    def test_get_trigger_tree_select_filter(self) -> None:
        tree = self.g.get_trigger_tree(
            [self.price],
            select=lambda f: f is self.total,
        )
        self.assertIn(self.total, tree.root)
        # partner_total filtered out → subtree should be empty/missing
        if self.partner_id in tree:
            subtree = tree[self.partner_id]
            self.assertNotIn(self.partner_total, subtree.root)

    def test_get_dependent_fields(self) -> None:
        deps = list(self.g.get_dependent_fields(self.price))
        self.assertIn(self.total, deps)
        self.assertIn(self.partner_total, deps)

    def test_get_dependent_fields_no_triggers(self) -> None:
        deps = list(self.g.get_dependent_fields(_field("unknown")))
        self.assertEqual(deps, [])

    def test_clear_caches(self) -> None:
        # Populate the cache
        self.g.get_field_trigger_tree(self.price)
        self.assertTrue(self.g._trigger_trees)
        # Clear
        self.g.clear_caches()
        self.assertFalse(self.g._trigger_trees)

    def test_has_triggers(self) -> None:
        self.assertTrue(self.g.has_triggers(self.price))
        self.assertFalse(self.g.has_triggers(self.total))


class TestIsModifyingRelations(unittest.TestCase):
    """Test is_modifying_relations() logic."""

    def test_relational_field_with_triggers(self) -> None:
        g = ModelGraph()
        m2o = _field("partner_id", type_="many2one", relational=True)
        dep = _field("partner_name", is_stored_computed=True)
        g.add_trigger(m2o, (), [dep])
        self.assertTrue(g.is_modifying_relations(m2o))

    def test_scalar_field_no_relational_deps(self) -> None:
        g = ModelGraph()
        scalar = _field("name")
        dep = _field("display_name", is_stored_computed=True)
        g.add_trigger(scalar, (), [dep])
        # scalar with no relational deps → False
        self.assertFalse(g.is_modifying_relations(scalar))

    def test_scalar_with_relational_dependent(self) -> None:
        g = ModelGraph()
        scalar = _field("code")
        dep = _field("ref_id", relational=True)
        g.add_trigger(scalar, (), [dep])
        # dep is relational → True
        self.assertTrue(g.is_modifying_relations(scalar))

    def test_field_with_inverses(self) -> None:
        g = ModelGraph()
        m2o = _field("partner_id", type_="many2one", relational=True)
        o2m = _field("order_ids", type_="one2many", relational=True)
        dep = _field("total")
        g.add_trigger(m2o, (), [dep])
        g._inverses[m2o] = (o2m,)
        self.assertTrue(g.is_modifying_relations(m2o))

    def test_no_triggers_is_false(self) -> None:
        g = ModelGraph()
        self.assertFalse(g.is_modifying_relations(_field("x")))

    def test_caches_result(self) -> None:
        g = ModelGraph()
        m2o = _field("partner_id", type_="many2one", relational=True)
        dep = _field("total")
        g.add_trigger(m2o, (), [dep])
        g._inverses[m2o] = (dep,)
        r1 = g.is_modifying_relations(m2o)
        r2 = g.is_modifying_relations(m2o)
        self.assertEqual(r1, r2)
        self.assertIn(m2o, g._modifying_relations)


# ---------------------------------------------------------------------------
# Transitive trigger closure tests
# ---------------------------------------------------------------------------


class TestTransitiveTriggers(unittest.TestCase):
    """Test that trigger trees compute the transitive closure correctly."""

    def test_chain_a_to_b_to_c(self) -> None:
        """A → B → C should produce a tree where A triggers both B and C."""
        g = ModelGraph()
        a = _field("a")
        b = _field("b", is_stored_computed=True)
        c = _field("c", is_stored_computed=True)
        g.add_trigger(a, (), [b])
        g.add_trigger(b, (), [c])

        g.get_field_trigger_tree(a)
        all_deps = list(g.get_dependent_fields(a))
        self.assertIn(b, all_deps)
        self.assertIn(c, all_deps)

    def test_cycle_detection(self) -> None:
        """Cycles in triggers should not cause infinite loops."""
        g = ModelGraph()
        a = _field("a")
        b = _field("b")
        g.add_trigger(a, (), [b])
        g.add_trigger(b, (), [a])

        # Should not hang
        tree = g.get_field_trigger_tree(a)
        self.assertTrue(tree)

    def test_diamond_dependency(self) -> None:
        """A → B, A → C, B → D, C → D should yield D once."""
        g = ModelGraph()
        a = _field("a")
        b = _field("b")
        c = _field("c")
        d = _field("d")
        g.add_trigger(a, (), [b, c])
        g.add_trigger(b, (), [d])
        g.add_trigger(c, (), [d])

        deps = list(g.get_dependent_fields(a))
        self.assertIn(b, deps)
        self.assertIn(c, deps)
        self.assertIn(d, deps)

    def test_deep_same_model_chain(self) -> None:
        """A long chain of same-model (empty-path) triggers resolves to a flat
        root holding every transitive target, in order, without duplicates.

        Regression: the closure walk and the per-node merge were both
        O(depth**2) (tuple ``seen`` copy + ``set(node.root)`` rebuilt on every
        merge), so a chain of same-model computed fields all accumulating at the
        root degraded sharply with depth. Build is now O(depth); this also
        exercises that path for correctness at depth.
        """
        g = ModelGraph()
        fields = [_field(f"f{i}") for i in range(200)]
        for i in range(len(fields) - 1):
            g.add_trigger(fields[i], (), [fields[i + 1]])

        tree = g.get_field_trigger_tree(fields[0])
        # all targets land on the root (empty path), once each, in chain order.
        # root is a tuple: nodes are shared registry-wide and must be immutable.
        self.assertEqual(tree.root, tuple(fields[1:]))
        self.assertEqual(len(tree.root), len(set(tree.root)))


# ---------------------------------------------------------------------------
# Path concatenation tests
# ---------------------------------------------------------------------------


class TestConcatPaths(unittest.TestCase):
    """Test _concat_paths m2o→o2m cancellation."""

    def test_simple_concat(self) -> None:
        a = _field("a")
        b = _field("b")
        result = _concat_paths((a,), (b,))
        self.assertEqual(result, (a, b))

    def test_empty_concat(self) -> None:
        self.assertEqual(_concat_paths((), ()), ())
        a = _field("a")
        self.assertEqual(_concat_paths((a,), ()), (a,))
        self.assertEqual(_concat_paths((), (a,)), (a,))

    def test_m2o_o2m_cancellation(self) -> None:
        """A many2one followed by its inverse one2many should cancel."""
        m2o = _field(
            "partner_id",
            model="order",
            type_="many2one",
            comodel_name="partner",
            relational=True,
        )
        o2m = _field(
            "order_ids",
            model="partner",
            type_="one2many",
            comodel_name="order",
            inverse_name="partner_id",
            relational=True,
        )
        result = _concat_paths((m2o,), (o2m,))
        self.assertEqual(result, ())

    def test_m2o_o2m_no_cancel_if_different_inverse(self) -> None:
        """Don't cancel if the o2m's inverse_name doesn't match the m2o's name."""
        m2o = _field(
            "partner_id",
            model="order",
            type_="many2one",
            comodel_name="partner",
            relational=True,
        )
        o2m = _field(
            "order_ids",
            model="partner",
            type_="one2many",
            comodel_name="order",
            inverse_name="other_id",
            relational=True,
        )
        result = _concat_paths((m2o,), (o2m,))
        self.assertEqual(result, (m2o, o2m))

    def test_m2o_o2m_no_cancel_if_different_models(self) -> None:
        """Don't cancel if the models don't match."""
        m2o = _field(
            "partner_id",
            model="order",
            type_="many2one",
            comodel_name="partner",
            relational=True,
        )
        o2m = _field(
            "order_ids",
            model="other_model",
            type_="one2many",
            comodel_name="order",
            inverse_name="partner_id",
            relational=True,
        )
        result = _concat_paths((m2o,), (o2m,))
        self.assertEqual(result, (m2o, o2m))


# ---------------------------------------------------------------------------
# discard_fields tests
# ---------------------------------------------------------------------------


class TestDiscardFields(unittest.TestCase):
    """Test removing fields from the graph."""

    def test_discard_from_triggers(self) -> None:
        g = ModelGraph()
        f = _field("price")
        t = _field("total")
        g.add_trigger(f, (), [t])
        g.discard_fields([f])
        self.assertFalse(g.has_triggers(f))

    def test_discard_from_triggers_as_target(self) -> None:
        # A discarded field must also be scrubbed where it is a trigger *target*
        # of another dep, else get_trigger_tree would schedule a deleted field.
        g = ModelGraph()
        dep = _field("price")
        gone = _field("total")
        kept = _field("subtotal")
        g.add_trigger(dep, (), [gone, kept])
        g.discard_fields([gone])
        tree = g.get_trigger_tree([dep])
        self.assertIn(kept, tree.root)
        self.assertNotIn(gone, tree.root)

    def test_discard_target_removes_emptied_dep(self) -> None:
        # If a dep's only targets are all discarded, the dep drops out entirely.
        g = ModelGraph()
        dep = _field("price")
        gone = _field("total")
        g.add_trigger(dep, (), [gone])
        g.discard_fields([gone])
        self.assertFalse(g.has_triggers(dep))

    def test_discard_from_depends(self) -> None:
        g = ModelGraph()
        f = _field("total")
        g._depends[f] = ("price",)
        g.discard_fields([f])
        self.assertNotIn(f, g.field_depends)

    def test_discard_from_inverses_key(self) -> None:
        g = ModelGraph()
        f = _field("partner_id")
        inv = _field("order_ids")
        g._inverses[f] = (inv,)
        g.discard_fields([f])
        self.assertNotIn(f, g.field_inverses)

    def test_discard_from_inverses_value(self) -> None:
        g = ModelGraph()
        f = _field("partner_id")
        inv = _field("order_ids")
        g._inverses[f] = (inv,)
        g.discard_fields([inv])
        # f still exists but inv is filtered out of its tuple
        self.assertNotIn(f, g.field_inverses)  # empty tuple → removed

    def test_discard_clears_caches(self) -> None:
        g = ModelGraph()
        f = _field("price")
        t = _field("total")
        g.add_trigger(f, (), [t])
        g.get_field_trigger_tree(f)  # populate cache
        g.discard_fields([f])
        self.assertFalse(g._trigger_trees)


# ---------------------------------------------------------------------------
# _Collector tests
# ---------------------------------------------------------------------------


class TestCollector(unittest.TestCase):
    """Test the lightweight _Collector dict subclass."""

    def test_missing_key_returns_empty_tuple(self) -> None:
        c = _Collector()
        self.assertEqual(c["nonexistent"], ())

    def test_setitem_stores_tuple(self) -> None:
        c = _Collector()
        c["key"] = [1, 2, 3]
        self.assertEqual(c["key"], (1, 2, 3))

    def test_setitem_removes_on_empty(self) -> None:
        c = _Collector()
        c["key"] = [1, 2]
        c["key"] = []
        self.assertNotIn("key", c)

    def test_add_appends(self) -> None:
        c = _Collector()
        c.add("key", "a")
        c.add("key", "b")
        self.assertEqual(c["key"], ("a", "b"))

    def test_add_deduplicates(self) -> None:
        c = _Collector()
        c.add("key", "a")
        c.add("key", "a")
        self.assertEqual(c["key"], ("a",))

    def test_discard_keys_and_values(self) -> None:
        c = _Collector()
        c["a"] = ("x", "y")
        c["b"] = ("x", "z")
        c["x"] = ("w",)
        c.discard_keys_and_values({"x"})
        self.assertNotIn("x", c)  # key removed
        self.assertEqual(c["a"], ("y",))  # value filtered
        self.assertEqual(c["b"], ("z",))

    def test_discard_removes_empty_after_filter(self) -> None:
        c = _Collector()
        c["a"] = ("x",)
        c.discard_keys_and_values({"x"})
        self.assertNotIn("a", c)  # became empty → removed

    def test_pop_works(self) -> None:
        c = _Collector()
        c["key"] = ("val",)
        result = c.pop("key", None)
        self.assertEqual(result, ("val",))
        self.assertNotIn("key", c)

    def test_clear_empties(self) -> None:
        c = _Collector()
        c["a"] = ("x",)
        c["b"] = ("y",)
        c.clear()
        self.assertEqual(len(c), 0)

    def test_get_returns_default(self) -> None:
        c = _Collector()
        self.assertEqual(c.get("missing"), None)
        self.assertEqual(c.get("missing", "default"), "default")

    def test_iteration(self) -> None:
        c = _Collector()
        c["a"] = ("x",)
        c["b"] = ("y",)
        self.assertEqual(set(c), {"a", "b"})


# ---------------------------------------------------------------------------
# Data ownership tests
# ---------------------------------------------------------------------------


class TestDataOwnership(unittest.TestCase):
    """Test that ModelGraph owns all field metadata collections."""

    def test_inverses_are_collector(self) -> None:
        g = ModelGraph()
        self.assertIsInstance(g._inverses, _Collector)

    def test_depends_are_collector(self) -> None:
        g = ModelGraph()
        self.assertIsInstance(g._depends, _Collector)

    def test_depends_context_are_collector(self) -> None:
        g = ModelGraph()
        self.assertIsInstance(g._depends_context, _Collector)

    def test_properties_delegate_to_internals(self) -> None:
        g = ModelGraph()
        self.assertIs(g.field_inverses, g._inverses)
        self.assertIs(g.field_depends, g._depends)
        self.assertIs(g.field_depends_context, g._depends_context)
        self.assertIs(g.field_computed, g._computed)

    def test_external_assignment_updates_property(self) -> None:
        """Simulates what Registry.field_inverses cached_property does:
        build a new Collector and assign it to model_graph._inverses.
        """
        g = ModelGraph()
        new_inverses = _Collector()
        f = _field("partner_id")
        inv = _field("order_ids")
        new_inverses[f] = (inv,)
        g._inverses = new_inverses
        self.assertIs(g.field_inverses, new_inverses)
        self.assertEqual(g.field_inverses[f], (inv,))

    def test_missing_key_returns_empty_tuple_via_property(self) -> None:
        """Ensure property delegation preserves _Collector's __getitem__ behavior."""
        g = ModelGraph()
        f = _field("nonexistent")
        self.assertEqual(g.field_inverses[f], ())
        self.assertEqual(g.field_depends[f], ())
        self.assertEqual(g.field_depends_context[f], ())


# ---------------------------------------------------------------------------
# Topological recompute order tests
# ---------------------------------------------------------------------------


class TestRecomputeOrder(unittest.TestCase):
    """Test _compute_recompute_order() topological sorting via Kahn's algorithm."""

    def _stored_computed(self, name: str, model: str = "m") -> MockField:
        """Create a mock field that looks like a stored computed field."""
        return _field(name, model=model, store=True, compute="_compute_" + name)

    def test_linear_chain_ordering(self) -> None:
        """A → B → C: priority(A) < priority(B) < priority(C)."""
        g = ModelGraph()
        a = self._stored_computed("a")
        b = self._stored_computed("b")
        c = self._stored_computed("c")
        g.add_trigger(a, (), [b])
        g.add_trigger(b, (), [c])

        order = g.recompute_order
        self.assertLess(order[a], order[b])
        self.assertLess(order[b], order[c])

    def test_diamond_dependencies(self) -> None:
        """A → B, A → C, B → D, C → D: A first, D last, B/C same level."""
        g = ModelGraph()
        a = self._stored_computed("a")
        b = self._stored_computed("b")
        c = self._stored_computed("c")
        d = self._stored_computed("d")
        g.add_trigger(a, (), [b, c])
        g.add_trigger(b, (), [d])
        g.add_trigger(c, (), [d])

        order = g.recompute_order
        self.assertLess(order[a], order[b])
        self.assertLess(order[a], order[c])
        self.assertLess(order[b], order[d])
        self.assertLess(order[c], order[d])
        # B and C should be at the same priority level
        self.assertEqual(order[b], order[c])

    def test_cycle_gets_max_priority(self) -> None:
        """A → B → A (cycle): both get the highest priority."""
        g = ModelGraph()
        a = self._stored_computed("a")
        b = self._stored_computed("b")
        g.add_trigger(a, (), [b])
        g.add_trigger(b, (), [a])

        order = g.recompute_order
        # Both should be present and get the same (max) priority
        self.assertIn(a, order)
        self.assertIn(b, order)
        self.assertEqual(order[a], order[b])

    def test_empty_graph(self) -> None:
        """No triggers → empty order dict."""
        g = ModelGraph()
        order = g.recompute_order
        self.assertEqual(order, {})

    def test_non_stored_fields_excluded(self) -> None:
        """Non-stored computed fields are not in the recompute order."""
        g = ModelGraph()
        source = self._stored_computed("source")
        non_stored = _field("non_stored", compute="_compute_ns", store=False)
        g.add_trigger(source, (), [non_stored])

        order = g.recompute_order
        self.assertNotIn(non_stored, order)

    def test_non_computed_fields_excluded(self) -> None:
        """Fields without compute are not in the recompute order."""
        g = ModelGraph()
        regular = _field("regular", store=True)  # no compute
        target = self._stored_computed("target")
        g.add_trigger(regular, (), [target])

        order = g.recompute_order
        # regular is not computed, should not be in order
        self.assertNotIn(regular, order)
        # target IS stored-computed, should be present
        self.assertIn(target, order)

    def test_caching(self) -> None:
        """recompute_order is computed once and cached."""
        g = ModelGraph()
        a = self._stored_computed("a")
        b = self._stored_computed("b")
        g.add_trigger(a, (), [b])

        order1 = g.recompute_order
        order2 = g.recompute_order
        self.assertIs(order1, order2)

    def test_cache_cleared_on_clear_caches(self) -> None:
        """clear_caches() invalidates the recompute order cache."""
        g = ModelGraph()
        a = self._stored_computed("a")
        b = self._stored_computed("b")
        g.add_trigger(a, (), [b])

        order1 = g.recompute_order
        g.clear_caches()
        order2 = g.recompute_order
        self.assertIsNot(order1, order2)
        # But values should be equal
        self.assertEqual(order1, order2)

    def test_mixed_cycle_and_chain(self) -> None:
        """A → B → C → B (cycle in B,C), A should be before B and C."""
        g = ModelGraph()
        a = self._stored_computed("a")
        b = self._stored_computed("b")
        c = self._stored_computed("c")
        g.add_trigger(a, (), [b])
        g.add_trigger(b, (), [c])
        g.add_trigger(c, (), [b])  # cycle

        order = g.recompute_order
        self.assertLess(order[a], order[b])
        self.assertLess(order[a], order[c])
        # B and C are in a cycle → same (max) priority
        self.assertEqual(order[b], order[c])

    def test_plain_column_feeding_computed_chain(self) -> None:
        """Plain column → total → grand_total (the canonical real shape).

        Regression lock for the simplification of ``_compute_recompute_order``
        (the dead ``dep_field in all_targets or ...`` disjunct was removed).
        Only stored-computed fields may appear in the order; a plain stored
        column that is a *dependency* of computed fields must never be ordered,
        and the computed chain must still sort dependency-before-dependent.
        """
        g = ModelGraph()
        column = _field("amount", store=True)  # plain column, no compute
        total = self._stored_computed("total")
        grand_total = self._stored_computed("grand_total")
        g.add_trigger(column, (), [total])  # non-computed dep → computed target
        g.add_trigger(total, (), [grand_total])  # computed dep → computed target

        order = g.recompute_order
        self.assertNotIn(column, order)  # never ordered: not stored-computed
        self.assertIn(total, order)
        self.assertIn(grand_total, order)
        self.assertLess(order[total], order[grand_total])

    def test_only_stored_computed_fields_in_order(self) -> None:
        """The order's keys are exactly the stored-computed fields, regardless
        of how many non-stored / non-computed fields trigger or are triggered.
        """
        g = ModelGraph()
        col = _field("col", store=True)  # plain column
        non_stored = _field("ns", store=False, compute="_c")  # computed, not stored
        sc = self._stored_computed("sc")
        g.add_trigger(col, (), [sc, non_stored])
        g.add_trigger(non_stored, (), [sc])  # non-stored dep feeding stored-computed

        order = g.recompute_order
        self.assertEqual(set(order), {sc})


class TestModelGraphFreeze(unittest.TestCase):
    """Test ModelGraph.freeze() — eager cache population for read-only querying.

    freeze() must (a) precompute every cache entry runtime queries can produce,
    so that (b) subsequent queries perform no cache mutation (the property that
    makes the process-shared graph safe to read concurrently / free-threaded),
    and (c) not change any query result versus lazy computation.
    """

    def _build_graph(self) -> ModelGraph:
        """A representative graph: scalar + relational deps, a stored-computed
        target (for recompute_order), a path-based trigger, and an inverse."""
        g = ModelGraph()
        price = _field("price")
        qty = _field("qty")
        partner_id = _field("partner_id", type_="many2one", relational=True)
        total = _field("total", is_stored_computed=True, store=True, compute="_c")
        partner_total = _field(
            "partner_total", is_stored_computed=True, store=True, compute="_c"
        )
        g.add_trigger(price, (), [total])
        g.add_trigger(qty, (), [total])
        g.add_trigger(price, (partner_id,), [partner_total])
        g.add_trigger(total, (), [partner_total])  # stored→stored, for ordering
        g._inverses[partner_id] = (partner_id,)
        return g

    def test_freeze_populates_all_caches(self) -> None:
        g = self._build_graph()
        self.assertEqual(g._trigger_trees, {})
        self.assertEqual(g._modifying_relations, {})
        self.assertIsNone(g._recompute_order)

        g.freeze()

        # Every field with triggers has a cached tree and modifying-relations.
        for field in g._triggers:
            self.assertIn(field, g._trigger_trees)
            self.assertIn(field, g._modifying_relations)
        self.assertIsNotNone(g._recompute_order)

    def test_queries_after_freeze_do_not_mutate(self) -> None:
        """The core race-freedom guarantee: post-freeze reads write nothing."""
        g = self._build_graph()
        g.freeze()

        trees_keys = set(g._trigger_trees)
        modrel_keys = set(g._modifying_relations)
        order_obj = g._recompute_order  # identity must not change (no recompute)

        # Exercise every public query path, including non-trigger fields and an
        # arbitrary multi-field set (the get_trigger_tree merge path).
        non_trigger = _field("unrelated")
        for field in list(g._triggers) + [non_trigger]:
            g.get_field_trigger_tree(field)
            g.is_modifying_relations(field)
            list(g.get_dependent_fields(field))
        g.get_trigger_tree(list(g._triggers) + [non_trigger])
        _ = g.recompute_order

        self.assertEqual(set(g._trigger_trees), trees_keys, "trigger-tree cache grew")
        self.assertEqual(
            set(g._modifying_relations), modrel_keys, "modifying-relations cache grew"
        )
        self.assertIs(g._recompute_order, order_obj, "recompute_order recomputed")

    def test_non_trigger_field_is_uncached(self) -> None:
        """A field with no triggers returns False without polluting the cache —
        the property that bounds the cache to a finite, freezable key set."""
        g = self._build_graph()
        g.freeze()
        x = _field("no_deps")
        self.assertFalse(g.is_modifying_relations(x))
        self.assertNotIn(x, g._modifying_relations)

    def test_freeze_is_idempotent(self) -> None:
        g = self._build_graph()
        g.freeze()
        trees, modrel, order = (
            dict(g._trigger_trees),
            dict(g._modifying_relations),
            dict(g.recompute_order),
        )
        g.freeze()
        self.assertEqual(set(g._trigger_trees), set(trees))
        self.assertEqual(g._modifying_relations, modrel)
        self.assertEqual(g.recompute_order, order)

    def test_freeze_preserves_query_results(self) -> None:
        """Freezing must not change any answer versus lazy computation."""
        eager = self._build_graph()
        eager.freeze()
        lazy = self._build_graph()  # identical graph, never frozen
        # Build matching field handles by name for comparison.
        for f_eager in eager._triggers:
            f_lazy = next(f for f in lazy._triggers if f.name == f_eager.name)
            self.assertEqual(
                eager.is_modifying_relations(f_eager),
                lazy.is_modifying_relations(f_lazy),
            )
            self.assertEqual(
                {d.name for d in eager.get_dependent_fields(f_eager)},
                {d.name for d in lazy.get_dependent_fields(f_lazy)},
            )
        self.assertEqual(
            {f.name: p for f, p in eager.recompute_order.items()},
            {f.name: p for f, p in lazy.recompute_order.items()},
        )


if __name__ == "__main__":
    unittest.main()
