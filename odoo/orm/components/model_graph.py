"""Standalone dependency graph for ORM fields.

:class:`ModelGraph` holds the field dependency graph (triggers, inverses,
computed groups, context dependencies). Helpers: :class:`TriggerTree`, the
backwards-traversal plan for recomputation, and :class:`_Collector`, a
key→tuple mapping. No dependency on Environment, BaseModel, or cursors —
testable with pure Python.

The graph is static after construction: built once when the registry loads,
then queried read-only. It is the single source of truth for field metadata —
Registry builds into it and delegates reads to it.

Concurrency model: trigger data and *every* cache derived from it (memoized
trigger trees, modifying-relations map, recompute order) live together in one
:class:`_TriggerState` snapshot, published by a single reference swap
(:meth:`ModelGraph.set_triggers` and friends). Lock-free readers grab the
current snapshot once per operation, so they always see a map and derived
caches that agree; published maps are never mutated in place (see
:meth:`ModelGraph.discard_fields`). A monotonic epoch plus an invalidation
barrier (:meth:`ModelGraph.begin_invalidation` /
:meth:`ModelGraph.end_invalidation`) lets registry teardowns refuse
publication to stale reader-triggered rebuilds.
"""

import threading
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator

    from ._protocols import FieldLike


# _Collector — lightweight key→tuple mapping


class _Collector(dict):
    """A mapping from keys to tuples, implementing a relation.

    Standalone equivalent of ``odoo.libs.collections.misc.Collector`` (the Odoo
    import is avoided to stay pure-Python testable). Semantically a
    ``defaultdict(tuple)`` with add and bulk-discard helpers.
    """

    __slots__ = ()

    def __getitem__(self, key: Any) -> tuple:
        return self.get(key, ())

    def __setitem__(self, key: Any, val: Any) -> None:
        val = tuple(val)
        if val:
            super().__setitem__(key, val)
        else:
            super().pop(key, None)

    def add(self, key: Any, val: Any) -> None:
        """Append *val* to the tuple for *key* (no-op if already present)."""
        vals = self[key]
        if val not in vals:
            self[key] = vals + (val,)

    def discard_keys_and_values(self, excludes: Any) -> None:
        """Remove *excludes* from both keys and values."""
        for key in excludes:
            self.pop(key, None)
        for key, vals in list(self.items()):
            self[key] = tuple(val for val in vals if val not in excludes)


# TriggerTree — pure data structure


class TriggerTree(dict):
    r"""Tree of field triggers for backwards dependency traversal.

    Each node holds ``root`` (fields to recompute when the trigger fires at this
    level) and ``{edge_field: subtree}`` entries for traversing backwards along
    relational fields.

    For instance, if G depends on F, H on X.F, I on W.X.F, and J on Y.F, the
    triggers of F form the tree::

                                     [G]
                                   X/   \\Y
                                 [H]     [J]
                               W/
                             [I]

    When F is modified on records, mark G on records, H on inverse(X, records),
    I on inverse(W, inverse(X, records)), and J on inverse(Y, records).
    """

    __slots__ = ("root",)
    root: Collection

    def __init__(self, root: Collection = (), *args: Any, **kwargs: Any) -> None:
        """Initialize the node with *root* fields and optional subtree entries.

        :param root: fields to recompute when the trigger fires at this node.
            Remaining arguments seed the ``{edge_field: subtree}`` dict.
        """
        super().__init__(*args, **kwargs)
        # tuple, not list: the single-tree fast path in merge() returns the
        # shared cached tree by identity, so a mutable root would let one
        # consumer corrupt the registry-wide, frozen trigger cache.
        self.root = tuple(root)

    def __bool__(self) -> bool:
        """Return whether the node has any root fields or subtrees."""
        return bool(self.root or len(self))

    def __repr__(self) -> str:
        """Return a representation showing the root fields and subtree entries."""
        return f"TriggerTree(root={self.root!r}, {super().__repr__()})"

    def increase(self, key: Any) -> TriggerTree:
        """Return the subtree for *key*, creating it if absent."""
        try:
            return self[key]
        except KeyError:
            subtree = self[key] = TriggerTree()
            return subtree

    def depth_first(self) -> Iterator[TriggerTree]:
        """Yield all nodes in depth-first order."""
        yield self
        for subtree in self.values():
            yield from subtree.depth_first()

    @classmethod
    def merge(cls, trees: list[TriggerTree], select: Callable = bool) -> TriggerTree:
        """Merge trigger trees into a single tree.

        *select* is called on every field; only those it keeps stay in the tree
        nodes (e.g. drop non-stored computed fields with no cached data).
        """
        # Fast path: single tree (common single-field write) — skip the merge
        # overhead and return the cached tree directly when possible.
        if len(trees) == 1:
            return trees[0]._filtered(select)

        root_fields: list[Any] = []
        subtrees_to_merge: dict[Any, list[TriggerTree]] = defaultdict(list)

        for tree in trees:
            root_fields.extend(tree.root)
            for label, subtree in tree.items():
                subtrees_to_merge[label].append(subtree)

        # deduplicate while preserving order
        seen: set[Any] = set()
        unique_root: list[Any] = []
        for field in root_fields:
            if field not in seen:
                seen.add(field)
                unique_root.append(field)

        result = cls([field for field in unique_root if select(field)])
        for label, subtrees in subtrees_to_merge.items():
            subtree = cls.merge(subtrees, select)
            if subtree:
                result[label] = subtree

        return result

    def _filtered(self, select: Callable) -> TriggerTree:
        """Return a *select*-filtered copy, or ``self`` if nothing was removed.

        Returns ``self`` (no allocation) when every root field passes *select*
        and every subtree is likewise unchanged — the common all-pass case on
        the single-tree ``merge()`` fast path, which previously deep-copied the
        whole cached tree whenever it had subtrees. Callers must treat the
        result as frozen either way (it may be the registry-shared cached
        tree; see :meth:`merge`).
        """
        root = self.root
        filtered_root = [f for f in root if select(f)]
        children_changed = False
        filtered_children: list[tuple[Any, TriggerTree]] = []
        for label, subtree in self.items():
            filtered_sub = subtree._filtered(select)
            if filtered_sub is not subtree:
                children_changed = True
            if filtered_sub:
                filtered_children.append((label, filtered_sub))
        if len(filtered_root) == len(root) and not children_changed:
            return self
        result = TriggerTree(filtered_root)
        for label, filtered_sub in filtered_children:
            result[label] = filtered_sub
        return result


# _TriggerState — one published snapshot of triggers + derived caches


class _TriggerState:
    """One published snapshot: the trigger map plus every derived cache.

    :class:`ModelGraph` publishes trigger data by swapping a single
    ``_TriggerState`` reference — one atomic attribute assignment. Lock-free
    readers capture the current state once per operation, so a trigger map is
    only ever observed together with derived caches built *from that same
    map*; there is no window where a fresh map is served with stale trees (or
    vice versa).

    The derived caches (``trees``, ``modifying_relations``,
    ``recompute_order``) start empty and fill lazily on first query (or
    eagerly via :meth:`ModelGraph.freeze`). Filling is a pure function of this
    state's own ``triggers``, so concurrent fills are idempotent: two threads
    racing a cold entry write identical values, and each dict/attribute store
    is atomic.
    """

    __slots__ = ("modifying_relations", "recompute_order", "trees", "triggers")

    def __init__(self, triggers: defaultdict) -> None:
        """Wrap *triggers* with fresh, empty derived caches."""
        # Raw trigger data: {dep_field: {path_tuple: list_of_target_fields}}
        self.triggers = triggers
        # Lazy per-field trigger-tree cache
        self.trees: dict[Any, TriggerTree] = {}
        # Lazy per-field is_modifying_relations cache
        self.modifying_relations: dict[Any, bool] = {}
        # Lazy topological priority map (None until first computed)
        self.recompute_order: dict[Any, int] | None = None


def _empty_triggers() -> defaultdict:
    """Return a fresh empty trigger map ``{dep_field: {path: [targets]}}``."""
    return defaultdict(lambda: defaultdict(list))


# ModelGraph — frozen dependency graph


class ModelGraph:
    """Frozen directed graph of field dependencies.

    Static after construction (all query methods read-only); built once when the
    registry loads, then shared immutably. Internal data structures:

    * ``_state``: the published :class:`_TriggerState` snapshot — the raw
      trigger map ``{dep_field: {path: list_of_target_fields}}`` plus every
      cache derived from it (trigger trees, modifying-relations, recompute
      order), swapped as one reference (see the module docstring)
    * ``_inverses``: ``{field: tuple_of_inverse_fields}``
    * ``_depends``: ``{field: tuple_of_dependency_fields}``
    * ``_depends_context``: ``{field: tuple_of_context_keys}``
    * ``_computed``: ``{field: list_of_co_computed_fields}``

    The metadata collectors (``_inverses``/``_depends``/``_depends_context``/
    ``_computed``) are *not* part of the snapshot: they are read by key lookup
    only (never iterated by request threads), and ``_depends_context`` must
    keep its object identity (see :meth:`reset_field_metadata`).
    """

    __slots__ = (
        "_computed",
        "_depends",
        "_depends_context",
        "_epoch",
        "_invalidation_barrier",
        "_inverses",
        "_publish_lock",
        "_state",
    )

    def __init__(self) -> None:
        """Initialize all dependency maps and an empty published snapshot."""
        # Field inverses: _Collector {field: tuple_of_inverse_fields}
        self._inverses: _Collector = _Collector()
        # Field dependencies: _Collector {field: tuple_of_dependency_fields}
        self._depends: _Collector = _Collector()
        # Context dependencies: _Collector {field: tuple_of_context_keys}
        self._depends_context: _Collector = _Collector()
        # Computed groups: {field: [field, co_field1, ...]}
        self._computed: dict[Any, list] = {}
        # Published snapshot: trigger map + derived caches, swapped atomically.
        self._state: _TriggerState = _TriggerState(_empty_triggers())
        # Publication epoch + invalidation barrier (see begin_invalidation).
        self._epoch: int = 0
        self._invalidation_barrier: bool = False
        # Serializes epoch/barrier updates against epoch-validated
        # publications. Writers only — readers never take it.
        self._publish_lock = threading.Lock()

    # Introspection properties — the current snapshot's structures.
    # Prefer the query API; these exist for the registry facade
    # (``Registry._field_triggers`` returns ``_triggers``) and for tests.

    @property
    def _triggers(self) -> defaultdict:
        """The current snapshot's raw trigger map (read-only by contract)."""
        return self._state.triggers

    @property
    def _trigger_trees(self) -> dict[Any, TriggerTree]:
        """The current snapshot's trigger-tree cache."""
        return self._state.trees

    @property
    def _modifying_relations(self) -> dict[Any, bool]:
        """The current snapshot's modifying-relations cache."""
        return self._state.modifying_relations

    @property
    def _recompute_order(self) -> dict[Any, int] | None:
        """The current snapshot's recompute order (None until computed)."""
        return self._state.recompute_order

    # Construction API

    def add_trigger(self, dep_field: Any, path: tuple, targets: Iterable) -> None:
        """Register that *targets* depend on *dep_field* via *path*.

        Construction-time API: mutates the currently-published map **in
        place**. Only use while the graph is not yet shared with concurrent
        readers (initial build, single-threaded tests). The concurrency-safe
        way to replace trigger data on a live graph is to build a complete map
        locally and publish it via :meth:`set_triggers`.

        :param dep_field: the dependency field (hashable key)
        :param path: tuple of relational fields to inverse-traverse
        :param targets: fields that need recomputation
        """
        bucket = self._state.triggers[dep_field][path]
        for target in targets:
            if target not in bucket:
                bucket.append(target)

    def reset_triggers(self) -> None:
        """Reset trigger data to empty state for rebuilding.

        Publishes a fresh empty snapshot (empty map + empty derived caches,
        swapped together), before incrementally adding triggers via
        :meth:`add_trigger`.
        """
        with self._publish_lock:
            self._state = _TriggerState(_empty_triggers())

    def set_triggers(self, triggers: defaultdict, *, epoch: int | None = None) -> bool:
        """Publish a fully-built trigger map atomically. Return whether it won.

        The map and its (empty, to-be-lazily-filled) derived caches are
        published together as one :class:`_TriggerState` swap, so a concurrent
        reader — or a thread racing the ``Registry._field_triggers``
        ``cached_property`` — can never observe an empty or partial map, nor a
        new map alongside trees derived from the old one.

        :param epoch: pass the :attr:`trigger_epoch` value captured *before*
            building *triggers* to make the publication conditional: it is
            refused (returns ``False``) when a registry invalidation has begun
            since (:meth:`begin_invalidation` bumped the epoch or the barrier
            is up), because the map may derive from half-set-up models and
            must not clobber the invalidator's own authoritative rebuild.
            ``None`` (construction/writer use, serialized by the registry
            lock) publishes unconditionally.
        :returns: ``True`` if the snapshot was published.
        """
        state = _TriggerState(triggers)
        with self._publish_lock:
            if epoch is not None and (
                self._invalidation_barrier or epoch != self._epoch
            ):
                return False
            self._state = state
        return True

    # Invalidation epoch — refuses stale publications during registry teardowns

    @property
    def trigger_epoch(self) -> int:
        """Monotonic publication epoch (see :meth:`begin_invalidation`).

        Capture it *before* building a trigger map, and pass it to
        :meth:`set_triggers` to publish conditionally.
        """
        return self._epoch

    def begin_invalidation(self) -> None:
        """Open a registry-teardown window: refuse epoch-validated publications.

        Called (under the registry's write lock) at the START of any teardown
        that changes the inputs triggers are built from — full/incremental
        model setup, custom-field discard — *before* model classes are
        mutated. Bumps the epoch (refusing rebuilds that started before the
        teardown) and raises the barrier (refusing rebuilds that start *during*
        it, which would otherwise capture the current epoch mid-mutation and
        publish garbage). Without this, a reader-triggered
        ``Registry._field_triggers`` rebuild racing the teardown could win the
        publication race *after* the teardown's own eager rebuild and publish
        triggers derived from half-set-up models.

        Balanced by :meth:`end_invalidation`. If a teardown dies in between,
        the barrier stays up: readers keep being served the last published
        (pre-teardown, internally consistent) snapshot until the next
        successful setup — the safest failure mode.
        """
        with self._publish_lock:
            self._epoch += 1
            self._invalidation_barrier = True

    def end_invalidation(self) -> None:
        """Close the teardown window opened by :meth:`begin_invalidation`.

        Called once the models are fully set up again, right before the
        teardown's own authoritative rebuild. Bumps the epoch once more (so
        rebuilds that started *during* the teardown stay refused forever) and
        drops the barrier (so the authoritative rebuild — and any rebuild
        started after this point — publishes normally).
        """
        with self._publish_lock:
            self._epoch += 1
            self._invalidation_barrier = False

    def reset_field_metadata(self) -> None:
        """Reset all field metadata collections to empty state.

        Called during full registry setup (``setup_models(model_names=None)``) to
        clear stale metadata before rebuilding. Does NOT clear triggers or caches.

        Clears **in place** rather than rebinding fresh objects, so live
        references survive the rebuild — notably ``_depends_context``, which is
        never reassigned elsewhere and is cached by
        ``Environment._field_depends_context`` (hot ``Field._get_cache`` path):
        rebinding it would orphan that cache, making context-dependence tests
        stale until every env is recreated. (``_inverses``/``_computed`` are also
        rebound by the registry's ``field_inverses``/``field_computed``
        cached_properties, so either style works for them.)
        """
        self._inverses.clear()
        self._depends.clear()
        self._depends_context.clear()
        self._computed.clear()

    def clear_caches(self) -> None:
        """Drop the derived caches (trigger trees, modifying relations, order).

        Publishes a new snapshot holding the *same* trigger map with fresh
        empty derived caches; a reader mid-operation keeps its previous
        (internally consistent) snapshot. Called when the registry is
        invalidated (e.g. field setup, module reload).
        """
        with self._publish_lock:
            self._state = _TriggerState(self._state.triggers)

    def discard_fields(self, fields: Collection) -> None:
        """Remove *fields* from the graph's data structures.

        Called when fields are removed from the registry (e.g. custom field
        deletion). Two different mutation disciplines apply:

        * The metadata collectors (``_depends``, ``_depends_context``,
          ``_computed``, ``_inverses``) are scrubbed **in place** — request
          threads read them by key lookup only, and ``_depends_context`` must
          keep its identity (see :meth:`reset_field_metadata`). Note that
          ``_computed`` only drops the discarded fields' *key* entries: the
          co-computed group lists (shared values) are not scrubbed here — the
          registry rebuilds the whole map from the model classes on the next
          ``field_computed`` access.
        * The trigger map is **never** mutated in place: request threads
          iterate it lock-free while building trigger trees, and an in-place
          scrub reliably crashes them with "dictionary changed size during
          iteration". Instead a scrubbed *copy* is built and published
          atomically as a fresh snapshot (map + empty derived caches in one
          swap). In production, ``Registry._discard_fields`` follows up with a
          full eager rebuild through ``_field_triggers`` — the real
          publication — but the copy-swap keeps the standalone graph correct
          and race-free on its own.
        """
        discarded = set(fields)
        for f in discarded:
            self._depends.pop(f, None)
            self._depends_context.pop(f, None)
            self._computed.pop(f, None)

        # Discard from inverses (keys and values)
        self._inverses.discard_keys_and_values(fields)

        # Copy-scrub-swap of the trigger map: drop discarded deps, and scrub
        # discarded fields where they appear as trigger *targets* of other deps
        # (``triggers`` is ``{dep: {path: [targets]}}``: dropping a field only
        # as a key would leave it reachable via ``get_trigger_tree(dep)``,
        # which would then schedule a deleted field). Emptied paths and deps
        # are dropped along the way. The published map is only read, never
        # written, so this iteration is safe against concurrent readers.
        old_triggers = self._state.triggers
        new_triggers = _empty_triggers()
        for dep, buckets in old_triggers.items():
            if dep in discarded:
                continue
            for path, targets in buckets.items():
                kept = [t for t in targets if t not in discarded]
                if kept:
                    new_triggers[dep][path] = kept

        with self._publish_lock:
            self._state = _TriggerState(new_triggers)

    # Query API — trigger trees
    #
    # Every public query grabs the published snapshot ONCE (``self._state``)
    # and threads it through the private ``*_for(state, ...)`` helpers, so one
    # operation never mixes structures from two publications.

    def has_triggers(self, field: Any) -> bool:
        """Return whether *field* has any dependents (is in the trigger map)."""
        return field in self._state.triggers

    def get_trigger_tree(
        self, fields: list[Any], select: Callable = bool
    ) -> TriggerTree:
        """Return the merged trigger tree for *fields*.

        The function *select* is called on every target field; only those
        for which it returns True are included.
        """
        state = self._state
        trees = [
            self._tree_for(state, field) for field in fields if field in state.triggers
        ]
        return TriggerTree.merge(trees, select)

    def get_field_trigger_tree(self, field: Any) -> TriggerTree:
        """Return the trigger tree for a single field.

        Computed lazily from the transitive closure of the snapshot's trigger
        map and cached in the same snapshot's tree cache.
        """
        return self._tree_for(self._state, field)

    def _tree_for(self, state: _TriggerState, field: Any) -> TriggerTree:
        """Return *field*'s trigger tree computed from and cached in *state*."""
        try:
            return state.trees[field]
        except KeyError:
            pass

        triggers = state.triggers
        if field not in triggers:
            return TriggerTree()

        # Walk the transitive closure once in pre-order, accumulating the
        # de-duplicated target list per full path. ``seen`` holds the current
        # path's fields to break cycles; it is a set with add/discard rather than
        # a per-level ``tuple`` copy (``seen + (field,)``), so a chain of depth d
        # costs O(d) membership tests instead of O(d**2). Targets for a path are
        # merged before recursing into them, matching the previous traversal's
        # emission order exactly (relevant when ``_concat_paths`` cancellation
        # routes a descendant back onto an ancestor's path).
        #
        # Memoization: without it the walk is O(2**depth) on diamond-shaped
        # dependency DAGs (A -> {B, C} -> D re-expands D once per incoming
        # path), because the per-path ``root_set`` dedups *emission* but not
        # *recursion*.  A repeated call with an identical ``(field, prefix)``
        # key re-merges exactly the same targets under exactly the same full
        # paths (both are functions of ``field``/``prefix``/``triggers`` only)
        # and re-recurses identically — a strict no-op on ``collected`` — so it
        # can be skipped, PROVIDED the cycle guard cannot interfere: the skip
        # is valid only when no field the memoized expansion ever reached
        # (``visited``) sits on the *current* ancestor path (``seen``), since
        # such a field would have been pruned this time around.  ``visited``
        # is prefix-independent (prefixes shape emitted paths, never the
        # recursion structure), so it is memoized per field.  Expansions that
        # were themselves pruned against an ancestor *outside* their own
        # subtree are context-dependent and never memoized (``clean=False``);
        # cyclic clusters therefore degrade to the plain traversal, while
        # acyclic graphs — the pathological case — collapse to one expansion
        # per distinct ``(field, prefix)`` pair.
        collected: dict[tuple, tuple[list, set]] = {}
        seen: set = set()
        expanded: set[tuple] = set()  # cleanly-expanded (field, prefix) keys
        visited_memo: dict[Any, frozenset] = {}  # field -> fields it reaches

        def collect(field: Any, prefix: tuple) -> frozenset | None:
            """Expand *field* under *prefix*.

            Returns the frozenset of fields the expansion recursed into when
            it was *clean* (pruned only inside its own subtree), or ``None``
            when it was pruned against an outer ancestor (context-dependent,
            not reusable).
            """
            if (field, prefix) in expanded:
                visited = visited_memo[field]
                if visited.isdisjoint(seen):
                    # Identical emissions already merged, identical recursion
                    # already performed, no cycle-guard interference: skip.
                    return visited
            seen.add(field)
            visited = {field}
            clean = True
            for path, targets in triggers[field].items():
                full_path = _concat_paths(prefix, path)
                entry = collected.get(full_path)
                if entry is None:
                    entry = ([], set())
                    collected[full_path] = entry
                root_list, root_set = entry
                for target in targets:
                    if target not in root_set:
                        root_set.add(target)
                        root_list.append(target)
                for target in targets:
                    if target in seen:
                        # Pruned. Inside this subtree (== in ``visited``, e.g.
                        # a self-loop) the prune is intrinsic and clean;
                        # against an outer ancestor it is context-dependent.
                        if target not in visited:
                            clean = False
                        continue
                    if target not in triggers:
                        continue
                    sub_visited = collect(target, full_path)
                    if sub_visited is None:
                        clean = False
                    else:
                        visited |= sub_visited
            seen.discard(field)
            if clean:
                result = frozenset(visited)
                visited_memo[field] = result
                expanded.add((field, prefix))
                return result
            return None

        collect(field, ())

        # Materialize the tree from the per-path lists. Building each node's root
        # once (the dedup happened above, incrementally) avoids the previous
        # O(n**2) merge that rebuilt ``set(node.root)`` on every emission — quadratic
        # when many targets land on one node (e.g. a chain of same-model computed
        # fields all accumulating at the root).
        tree = TriggerTree()
        for full_path, (root_list, _root_set) in collected.items():
            current = tree
            for label in full_path:
                current = current.increase(label)
            current.root = tuple(root_list)

        state.trees[field] = tree
        return tree

    def get_dependent_fields(self, field: Any) -> Iterator[Any]:
        """Return an iterable of all fields that depend on *field*."""
        return self._dependent_fields_for(self._state, field)

    def _dependent_fields_for(self, state: _TriggerState, field: Any) -> Iterator[Any]:
        """Yield the fields depending on *field*, per *state*'s trigger map."""
        if field not in state.triggers:
            return
        for tree in self._tree_for(state, field).depth_first():
            yield from tree.root

    def is_modifying_relations(self, field: Any) -> bool:
        """Return whether modifying *field* might change dependent records.

        True if *field* has triggers AND (field is relational, or has
        inverses, or any of its dependents are relational / have inverses).
        """
        return self._modifying_relations_for(self._state, field)

    def _modifying_relations_for(self, state: _TriggerState, field: Any) -> bool:
        """:meth:`is_modifying_relations` against a given snapshot."""
        if field not in state.triggers:
            # No dependents → cannot modify relations. Returned *uncached* so
            # the cache only ever holds fields in the trigger map (a finite,
            # precomputable set); this is what lets :meth:`freeze` make the
            # cache complete and the graph truly read-only at runtime. The
            # membership test is O(1), so not caching the False costs nothing.
            return False

        try:
            return state.modifying_relations[field]
        except KeyError:
            pass

        result = bool(
            _is_relational(field)
            or self._inverses.get(field, ())
            or any(
                _is_relational(dep) or self._inverses.get(dep, ())
                for dep in self._dependent_fields_for(state, field)
            )
        )
        state.modifying_relations[field] = result
        return result

    # Topological ordering for recomputation

    @property
    def recompute_order(self) -> dict[Any, int]:
        """Return a priority map ``{field: int}`` for recomputation ordering.

        Fields with lower priority values should be recomputed first. The
        contract: if field B (transitively) depends on field A and A and B are
        not part of the same dependency cycle, then ``order[A] < order[B]``.
        All fields of one cycle (strongly connected component) share a single
        priority — the convergence loop handles intra-cycle ordering — and
        fields *downstream* of a cycle still order strictly after it.

        Computed lazily from the snapshot's trigger map via Kahn's algorithm
        on the SCC condensation (see :meth:`_compute_recompute_order`), and
        cached in the snapshot.

        Used by :class:`UnitOfWork` to process pending recomputations in
        dependency order, reducing the number of convergence iterations
        from O(depth) to O(1) for acyclic dependency chains.
        """
        state = self._state
        order = state.recompute_order
        if order is None:
            order = state.recompute_order = self._compute_recompute_order(
                state.triggers
            )
        return order

    @staticmethod
    def _compute_recompute_order(
        triggers: defaultdict,
    ) -> dict[FieldLike, int]:
        """Compute the topological ordering of stored-computed fields.

        Kahn's BFS over the strongly-connected-component condensation (Tarjan)
        of the trigger graph: every dependency cycle collapses into one
        condensation node, so cycle members share their component's priority
        while every acyclic region — including fields downstream of a cycle —
        keeps strict topological order. (A plain Kahn drain can never reach
        nodes downstream of a cycle, which used to flatten that whole region
        to one max priority and cost O(chain depth) convergence passes.)

        Only stored-computed target fields from the trigger map participate
        (non-stored computed fields are invalidated, not recomputed).

        Returns ``{field: priority_int}`` where lower = should compute first.
        """
        # Collect all stored-computed fields that appear as trigger targets
        all_targets: set[FieldLike] = set()
        for dep_field, paths in triggers.items():
            for targets in paths.values():
                for target in targets:
                    # ``store``/``compute`` are guaranteed by the ``FieldLike``
                    # protocol, so read them directly: a defensive ``getattr``
                    # would silently mask a missing attribute as "not
                    # stored-computed" and drop the field from the ordering —
                    # the exact failure mode the protocol exists to prevent.
                    if target.store and target.compute:
                        all_targets.add(target)
                        # A dep_field that is itself stored-computed is also a
                        # node in the ordering.  (The former `dep_field in
                        # all_targets or ...` disjunct was dead: `all_targets`
                        # only ever holds stored-computed fields, so membership
                        # already implied the store/compute test below.)
                        if dep_field.store and dep_field.compute:
                            all_targets.add(dep_field)

        # Build adjacency: dep_field → target means "when dep_field changes,
        # target needs recomputation", so dep_field must be computed first.
        adjacency: dict[FieldLike, set[FieldLike]] = {
            field: set() for field in all_targets
        }
        for dep_field, paths in triggers.items():
            if dep_field not in all_targets:
                continue
            dep_adjacency = adjacency[dep_field]
            for targets in paths.values():
                for target in targets:
                    if target in all_targets and target is not dep_field:
                        dep_adjacency.add(target)

        # Condense to the SCC graph (acyclic by construction).
        sccs = _strongly_connected_components(adjacency)
        component_of: dict[FieldLike, int] = {}
        for component_index, component in enumerate(sccs):
            for field in component:
                component_of[field] = component_index
        component_adjacency: list[set[int]] = [set() for _ in sccs]
        component_in_degree: list[int] = [0] * len(sccs)
        for field, dependents in adjacency.items():
            source = component_of[field]
            source_adjacency = component_adjacency[source]
            for dependent in dependents:
                sink = component_of[dependent]
                if sink != source and sink not in source_adjacency:
                    source_adjacency.add(sink)
                    component_in_degree[sink] += 1

        # Kahn's BFS on the condensation. A DAG always drains completely, so
        # every field is ordered — no fallback bucket needed.
        queue: list[int] = [
            index for index, degree in enumerate(component_in_degree) if degree == 0
        ]
        order: dict[FieldLike, int] = {}
        priority = 0
        while queue:
            # Process all components at this priority level
            next_queue: list[int] = []
            for index in queue:
                for field in sccs[index]:
                    order[field] = priority
                for sink in component_adjacency[index]:
                    component_in_degree[sink] -= 1
                    if component_in_degree[sink] == 0:
                        next_queue.append(sink)
            queue = next_queue
            priority += 1

        return order

    # Freeze — eager cache population for read-only / free-threaded querying

    def freeze(self) -> None:
        """Eagerly populate the lazy caches, making the graph truly read-only.

        The class contract is that the graph is *static after construction* (see
        the module docstring), yet the trigger-tree, modifying-relations and
        recompute-order caches fill lazily on first query — so the first read of
        each *mutates* the process-shared graph. On free-threaded CPython (PEP
        703) this stays correct (the dict operations are individually
        thread-safe), but N threads racing a cold cache each redundantly rebuild
        the same entries before the last write wins.

        Calling ``freeze()`` once, right after the registry builds the trigger
        graph (see ``Registry._field_triggers``), precomputes every entry runtime
        queries can produce, so subsequent reads are pure lookups with no rebuild
        and no mutation — removing the redundant work and making the "static
        after construction" contract literally true.

        Idempotent. Must be re-run after any publication that resets the
        derived caches (``clear_caches`` / ``reset_triggers`` /
        ``set_triggers`` / ``discard_fields``); the registry does this
        whenever it rebuilds the graph. Fills the snapshot that is current
        when it starts; a snapshot published mid-freeze simply starts cold
        again (its own rebuild re-freezes).
        """
        state = self._state
        for field in state.triggers:
            # Order matters: prime the trigger tree first so the
            # ``is_modifying_relations`` traversal of dependents hits the cache.
            self._tree_for(state, field)
            self._modifying_relations_for(state, field)
        if state.recompute_order is None:
            state.recompute_order = self._compute_recompute_order(state.triggers)

    # Direct access — backward-compatible properties

    @property
    def field_inverses(self) -> _Collector:
        """Direct access to the inverses mapping."""
        return self._inverses

    @property
    def field_depends(self) -> _Collector:
        """Direct access to the field dependencies mapping."""
        return self._depends

    @property
    def field_depends_context(self) -> _Collector:
        """Direct access to the context dependencies mapping."""
        return self._depends_context

    @property
    def field_computed(self) -> dict[Any, list]:
        """Direct access to the computed-groups mapping."""
        return self._computed


# Internal helpers


def _strongly_connected_components(
    adjacency: dict[Any, set[Any]],
) -> list[list[Any]]:
    """Return the strongly connected components of a directed graph.

    Tarjan's algorithm, iterative (an explicit work stack, so deep dependency
    chains cannot hit the recursion limit). Every node must appear as a key of
    *adjacency* (successor sets may be empty). Components are returned as
    lists of nodes; single nodes without a self-loop form singleton components.
    """
    index_of: dict[Any, int] = {}
    lowlink: dict[Any, int] = {}
    on_stack: set[Any] = set()
    stack: list[Any] = []
    components: list[list[Any]] = []
    next_index = 0

    for root, root_successors in adjacency.items():
        if root in index_of:
            continue
        index_of[root] = lowlink[root] = next_index
        next_index += 1
        stack.append(root)
        on_stack.add(root)
        # (node, resumable successor iterator) frames of the explicit DFS
        work: list[tuple[Any, Iterator[Any]]] = [(root, iter(root_successors))]
        while work:
            node, successors = work[-1]
            advanced = False
            for successor in successors:
                if successor not in index_of:
                    index_of[successor] = lowlink[successor] = next_index
                    next_index += 1
                    stack.append(successor)
                    on_stack.add(successor)
                    work.append((successor, iter(adjacency[successor])))
                    advanced = True
                    break
                if successor in on_stack and index_of[successor] < lowlink[node]:
                    lowlink[node] = index_of[successor]
            if advanced:
                continue
            # node's successors are exhausted: finish it
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])
            if lowlink[node] == index_of[node]:
                component: list[Any] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member is node:
                        break
                components.append(component)

    return components


def _concat_paths(seq1: tuple, seq2: tuple) -> tuple:
    """Concatenate two path segments, cancelling m2o→o2m round-trips.

    When a many2one field at the end of *seq1* is immediately followed by
    its inverse one2many at the start of *seq2*, the pair cancels out
    (navigating to the parent then back to children is a no-op).
    """
    if seq1 and seq2:
        f1, f2 = seq1[-1], seq2[0]
        if (
            _field_type(f1) == "many2one"
            and _field_type(f2) == "one2many"
            and _field_attr(f2, "inverse_name") == _field_attr(f1, "name")
            and _field_attr(f1, "model_name") == _field_attr(f2, "comodel_name")
            and _field_attr(f1, "comodel_name") == _field_attr(f2, "model_name")
        ):
            return _concat_paths(seq1[:-1], seq2[1:])
    return seq1 + seq2


def _field_type(field: FieldLike) -> str:
    """Return the field's type discriminator (e.g. ``"many2one"``)."""
    return field.type


def _field_attr(field: Any, attr: str) -> Any:
    """Get an arbitrary field attribute by name, or ``None`` if absent.

    Stays ``Any``/``getattr`` on purpose: it reads attributes *outside* the
    :class:`FieldLike` contract (``name``, ``inverse_name``, ``comodel_name``)
    during inverse-pair detection.
    """
    return getattr(field, attr, None)


def _is_relational(field: FieldLike) -> bool:
    """Whether the field is relational (has a comodel)."""
    return field.relational
