"""Standalone dependency graph for ORM fields.

:class:`ModelGraph` holds the field dependency graph (triggers, inverses,
computed groups, context dependencies). Helpers: :class:`TriggerTree`, the
backwards-traversal plan for recomputation, and :class:`_Collector`, a
key→tuple mapping. No dependency on Environment, BaseModel, or cursors —
testable with pure Python.

The graph is static after construction: built once when the registry loads,
then queried read-only. It is the single source of truth for field metadata —
Registry builds into it and delegates reads to it.
"""

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

        Avoids allocations when all root fields pass *select*.
        """
        root = self.root
        filtered_root = [f for f in root if select(f)]
        # Root-only tree (no subtrees) where all fields pass: return self
        if len(filtered_root) == len(root) and not len(self):
            return self
        result = TriggerTree(filtered_root)
        for label, subtree in self.items():
            filtered_sub = subtree._filtered(select)
            if filtered_sub:
                result[label] = filtered_sub
        return result


# ModelGraph — frozen dependency graph


class ModelGraph:
    """Frozen directed graph of field dependencies.

    Static after construction (all query methods read-only); built once when the
    registry loads, then shared immutably. Internal data structures:

    * ``_triggers``: raw trigger data —
      ``{dep_field: {path: list_of_target_fields}}``
    * ``_inverses``: ``{field: tuple_of_inverse_fields}``
    * ``_depends``: ``{field: tuple_of_dependency_fields}``
    * ``_depends_context``: ``{field: tuple_of_context_keys}``
    * ``_computed``: ``{field: list_of_co_computed_fields}``

    ``_trigger_trees`` is a lazy per-field cache built from ``_triggers``.
    """

    __slots__ = (
        "_computed",
        "_depends",
        "_depends_context",
        "_inverses",
        "_modifying_relations",
        "_recompute_order",
        "_trigger_trees",
        "_triggers",
    )

    def __init__(self) -> None:
        """Initialize all dependency maps and lazy caches empty."""
        # Raw trigger data: {dep_field: {path_tuple: list_of_target_fields}}
        self._triggers: defaultdict[Any, defaultdict[tuple, list]] = defaultdict(
            lambda: defaultdict(list)
        )
        # Field inverses: _Collector {field: tuple_of_inverse_fields}
        self._inverses: _Collector = _Collector()
        # Field dependencies: _Collector {field: tuple_of_dependency_fields}
        self._depends: _Collector = _Collector()
        # Context dependencies: _Collector {field: tuple_of_context_keys}
        self._depends_context: _Collector = _Collector()
        # Computed groups: {field: [field, co_field1, ...]}
        self._computed: dict[Any, list] = {}
        # Lazy caches
        self._trigger_trees: dict[Any, TriggerTree] = {}
        self._modifying_relations: dict[Any, bool] = {}
        self._recompute_order: dict[Any, int] | None = None

    # Construction API

    def add_trigger(self, dep_field: Any, path: tuple, targets: Iterable) -> None:
        """Register that *targets* depend on *dep_field* via *path*.

        :param dep_field: the dependency field (hashable key)
        :param path: tuple of relational fields to inverse-traverse
        :param targets: fields that need recomputation
        """
        bucket = self._triggers[dep_field][path]
        for target in targets:
            if target not in bucket:
                bucket.append(target)

    def reset_triggers(self) -> None:
        """Reset trigger data to empty state for rebuilding.

        Called at the start of trigger construction (Registry._field_triggers)
        before incrementally adding triggers via :meth:`add_trigger`.
        Also clears the lazily-computed trigger tree caches.
        """
        self._triggers = defaultdict(lambda: defaultdict(list))
        self.clear_caches()

    def set_triggers(self, triggers: defaultdict) -> None:
        """Publish a fully-built trigger map atomically, then drop derived caches.

        Swapping ``_triggers`` in one assignment (rather than ``reset_triggers`` +
        incremental ``add_trigger`` on the live graph) means a concurrent reader —
        or a thread racing the ``Registry._field_triggers`` ``cached_property`` —
        never observes an empty or partial map. Derived caches are cleared *after*
        the swap, so any rebuild they trigger reads the complete new map.
        """
        self._triggers = triggers
        self.clear_caches()

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
        """Clear the lazily-computed caches (trigger trees, modifying relations).

        Called when the registry is invalidated (e.g. field setup, module reload).
        """
        self._trigger_trees.clear()
        self._modifying_relations.clear()
        self._recompute_order = None

    def discard_fields(self, fields: Collection) -> None:
        """Remove *fields* from all internal data structures.

        Called when fields are removed from the registry (e.g. custom field
        deletion).  Also clears trigger caches.
        """
        discarded = set(fields)
        for f in discarded:
            self._depends.pop(f, None)
            self._depends_context.pop(f, None)
            self._computed.pop(f, None)
            self._triggers.pop(f, None)

        # Also scrub discarded fields where they appear as trigger *targets* of
        # other deps (``_triggers`` is ``{dep: {path: [targets]}}``): popping a
        # field only as a key leaves it reachable via ``get_trigger_tree(dep)``,
        # which would then schedule a deleted field. Drop emptied paths and deps.
        for dep in list(self._triggers):
            buckets = self._triggers[dep]
            for path, targets in list(buckets.items()):
                kept = [t for t in targets if t not in discarded]
                if len(kept) == len(targets):
                    continue
                if kept:
                    buckets[path] = kept
                else:
                    del buckets[path]
            if not buckets:
                del self._triggers[dep]

        # Discard from inverses (keys and values)
        self._inverses.discard_keys_and_values(fields)

        self.clear_caches()

    # Query API — trigger trees

    def has_triggers(self, field: Any) -> bool:
        """Return whether *field* has any dependents (is in the trigger map)."""
        return field in self._triggers

    def get_trigger_tree(
        self, fields: list[Any], select: Callable = bool
    ) -> TriggerTree:
        """Return the merged trigger tree for *fields*.

        The function *select* is called on every target field; only those
        for which it returns True are included.
        """
        trees = [
            self.get_field_trigger_tree(field)
            for field in fields
            if field in self._triggers
        ]
        return TriggerTree.merge(trees, select)

    def get_field_trigger_tree(self, field: Any) -> TriggerTree:
        """Return the trigger tree for a single field.

        Computed lazily from the transitive closure of ``_triggers`` and
        cached in ``_trigger_trees``.
        """
        try:
            return self._trigger_trees[field]
        except KeyError:
            pass

        triggers = self._triggers
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
        collected: dict[tuple, tuple[list, set]] = {}
        seen: set = set()

        def collect(field: Any, prefix: tuple) -> None:
            if field in seen or field not in triggers:
                return
            seen.add(field)
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
                    collect(target, full_path)
            seen.discard(field)

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

        self._trigger_trees[field] = tree
        return tree

    def get_dependent_fields(self, field: Any) -> Iterator[Any]:
        """Return an iterable of all fields that depend on *field*."""
        if field not in self._triggers:
            return
        for tree in self.get_field_trigger_tree(field).depth_first():
            yield from tree.root

    def is_modifying_relations(self, field: Any) -> bool:
        """Return whether modifying *field* might change dependent records.

        True if *field* has triggers AND (field is relational, or has
        inverses, or any of its dependents are relational / have inverses).
        """
        if field not in self._triggers:
            # No dependents → cannot modify relations. Returned *uncached* so
            # the cache only ever holds fields in ``_triggers`` (a finite,
            # precomputable set); this is what lets :meth:`freeze` make the
            # cache complete and the graph truly read-only at runtime. The
            # membership test is O(1), so not caching the False costs nothing.
            return False

        try:
            return self._modifying_relations[field]
        except KeyError:
            pass

        result = bool(
            _is_relational(field)
            or self._inverses.get(field, ())
            or any(
                _is_relational(dep) or self._inverses.get(dep, ())
                for dep in self.get_dependent_fields(field)
            )
        )
        self._modifying_relations[field] = result
        return result

    # Topological ordering for recomputation

    @property
    def recompute_order(self) -> dict[Any, int]:
        """Return a priority map ``{field: int}`` for recomputation ordering.

        Fields with lower priority values should be recomputed first.
        Dependencies come before their dependents — if field B depends on
        field A, then ``order[A] < order[B]``.

        Computed lazily from ``_triggers`` via Kahn's algorithm (BFS
        topological sort).  Cycles are broken by assigning equal priority
        to all fields in the cycle — the convergence loop handles those.

        Used by :class:`UnitOfWork` to process pending recomputations in
        dependency order, reducing the number of convergence iterations
        from O(depth) to O(1) for acyclic dependency chains.
        """
        if self._recompute_order is None:
            self._recompute_order = self._compute_recompute_order()
        return self._recompute_order

    def _compute_recompute_order(self) -> dict[Any, int]:
        """Compute topological ordering of stored-computed fields.

        Uses Kahn's algorithm: fields with no unsatisfied dependencies
        are processed first, then their dependents become available.

        Only considers stored-computed target fields from the trigger map
        (non-stored computed fields are invalidated, not recomputed).

        Returns ``{field: priority_int}`` where lower = should compute first.
        """
        # Build adjacency: field → set of fields it triggers (direct dependents)
        # Only from stored-computed trigger targets (root-level in trigger trees)
        adjacency: dict[Any, set] = {}  # field → set of direct dependents
        in_degree: dict[Any, int] = {}  # field → number of dependencies

        # Collect all stored-computed fields that appear as trigger targets
        all_targets: set[Any] = set()
        for dep_field, paths in self._triggers.items():
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

        # Initialize
        for field in all_targets:
            adjacency.setdefault(field, set())
            in_degree.setdefault(field, 0)

        # Build edges: dep_field → target means "when dep_field changes,
        # target needs recomputation".  So dep_field must be computed first.
        for dep_field, paths in self._triggers.items():
            if dep_field not in all_targets:
                continue
            for targets in paths.values():
                for target in targets:
                    if target in all_targets and target is not dep_field:
                        if target not in adjacency.get(dep_field, ()):
                            adjacency.setdefault(dep_field, set()).add(target)
                            in_degree[target] = in_degree.get(target, 0) + 1

        # Kahn's BFS
        queue: list[Any] = [f for f in all_targets if in_degree.get(f, 0) == 0]
        order: dict[Any, int] = {}
        priority = 0

        while queue:
            # Process all fields at this priority level
            next_queue = []
            for field in queue:
                order[field] = priority
                for dependent in adjacency.get(field, ()):
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        next_queue.append(dependent)
            queue = next_queue
            priority += 1

        # Fields in cycles get max priority (processed last, convergence
        # loop handles them).  This is safe because cycles are rare and
        # the existing loop already handles them.
        for field in all_targets:
            if field not in order:
                order[field] = priority

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

        Idempotent. Must be re-run after any cache invalidation
        (``clear_caches`` / ``reset_triggers`` / ``discard_fields``); the registry
        does this whenever it rebuilds the graph.
        """
        for field in self._triggers:
            # Order matters: prime the trigger tree first so the
            # ``is_modifying_relations`` traversal of dependents hits the cache.
            self.get_field_trigger_tree(field)
            self.is_modifying_relations(field)
        self.recompute_order  # noqa: B018 — force the single shared order dict

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
