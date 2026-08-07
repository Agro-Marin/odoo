import threading
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from odoo.libs.collections import Collector

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator

    from ._protocols import FieldLike


_Collector = Collector


class TriggerTree(dict):
    __slots__ = ("root",)
    root: Collection

    def __init__(self, root: Collection = (), *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.root = tuple(root)

    def __bool__(self) -> bool:
        return bool(self.root or len(self))

    def __repr__(self) -> str:
        return f"TriggerTree(root={self.root!r}, {super().__repr__()})"

    def increase(self, key: Any) -> TriggerTree:
        try:
            return self[key]
        except KeyError:
            subtree = self[key] = TriggerTree()
            return subtree

    def depth_first(self) -> Iterator[TriggerTree]:
        yield self
        for subtree in self.values():
            yield from subtree.depth_first()

    @classmethod
    def merge(cls, trees: list[TriggerTree], select: Callable = bool) -> TriggerTree:
        if len(trees) == 1:
            return trees[0]._filtered(select)

        root_fields: list[Any] = []
        subtrees_to_merge: dict[Any, list[TriggerTree]] = defaultdict(list)

        for tree in trees:
            root_fields.extend(tree.root)
            for label, subtree in tree.items():
                subtrees_to_merge[label].append(subtree)

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


class _TriggerState:
    __slots__ = ("modifying_relations", "recompute_order", "trees", "triggers")

    def __init__(self, triggers: defaultdict) -> None:
        self.triggers = triggers
        self.trees: dict[Any, TriggerTree] = {}
        self.modifying_relations: dict[Any, bool] = {}
        self.recompute_order: dict[Any, int] | None = None


def _empty_triggers() -> defaultdict:
    return defaultdict(lambda: defaultdict(list))


class ModelGraph:
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
        self._inverses: _Collector = _Collector()
        self._depends: _Collector = _Collector()
        self._depends_context: _Collector = _Collector()
        self._computed: dict[Any, list] = {}
        self._state: _TriggerState = _TriggerState(_empty_triggers())
        self._epoch: int = 0
        self._invalidation_barrier: bool = False
        self._publish_lock = threading.Lock()

    @property
    def _triggers(self) -> defaultdict:
        return self._state.triggers

    @property
    def _trigger_trees(self) -> dict[Any, TriggerTree]:
        return self._state.trees

    @property
    def _modifying_relations(self) -> dict[Any, bool]:
        return self._state.modifying_relations

    @property
    def _recompute_order(self) -> dict[Any, int] | None:
        return self._state.recompute_order

    def add_trigger(self, dep_field: Any, path: tuple, targets: Iterable) -> None:
        bucket = self._state.triggers[dep_field][path]
        for target in targets:
            if target not in bucket:
                bucket.append(target)

    def reset_triggers(self) -> None:
        with self._publish_lock:
            self._state = _TriggerState(_empty_triggers())

    def set_triggers(self, triggers: defaultdict, *, epoch: int | None = None) -> bool:
        state = _TriggerState(triggers)
        with self._publish_lock:
            if epoch is not None and (
                self._invalidation_barrier or epoch != self._epoch
            ):
                return False
            self._state = state
        return True

    @property
    def trigger_epoch(self) -> int:
        return self._epoch

    def begin_invalidation(self) -> None:
        with self._publish_lock:
            self._epoch += 1
            self._invalidation_barrier = True

    def end_invalidation(self) -> None:
        with self._publish_lock:
            self._epoch += 1
            self._invalidation_barrier = False

    def reset_field_metadata(self) -> None:
        self._inverses.clear()
        self._depends.clear()
        self._depends_context.clear()
        self._computed.clear()

    def clear_caches(self) -> None:
        with self._publish_lock:
            self._state = _TriggerState(self._state.triggers)

    def discard_fields(self, fields: Collection) -> None:
        discarded = set(fields)
        for f in discarded:
            self._depends.pop(f, None)
            self._depends_context.pop(f, None)
            self._computed.pop(f, None)

        self._inverses.discard_keys_and_values(fields)

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

    def has_triggers(self, field: Any) -> bool:
        return field in self._state.triggers

    def get_trigger_tree(
        self, fields: list[Any], select: Callable = bool
    ) -> TriggerTree:
        state = self._state
        trees = [
            self._tree_for(state, field) for field in fields if field in state.triggers
        ]
        return TriggerTree.merge(trees, select)

    def get_field_trigger_tree(self, field: Any) -> TriggerTree:
        return self._tree_for(self._state, field)

    def _tree_for(self, state: _TriggerState, field: Any) -> TriggerTree:
        try:
            return state.trees[field]
        except KeyError:
            pass

        triggers = state.triggers
        if field not in triggers:
            return TriggerTree()

        collected: dict[tuple, tuple[list, set]] = {}
        seen: set = set()
        expanded: set[tuple] = set()
        visited_memo: dict[Any, frozenset] = {}

        def collect(field: Any, prefix: tuple) -> frozenset | None:
            if (field, prefix) in expanded:
                visited = visited_memo[field]
                if visited.isdisjoint(seen):
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

        tree = TriggerTree()
        for full_path, (root_list, _root_set) in collected.items():
            current = tree
            for label in full_path:
                current = current.increase(label)
            current.root = tuple(root_list)

        state.trees[field] = tree
        return tree

    def get_dependent_fields(self, field: Any) -> Iterator[Any]:
        return self._dependent_fields_for(self._state, field)

    def _dependent_fields_for(self, state: _TriggerState, field: Any) -> Iterator[Any]:
        if field not in state.triggers:
            return
        for tree in self._tree_for(state, field).depth_first():
            yield from tree.root

    def is_modifying_relations(self, field: Any) -> bool:
        return self._modifying_relations_for(self._state, field)

    def _modifying_relations_for(self, state: _TriggerState, field: Any) -> bool:
        if field not in state.triggers:
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

    @property
    def recompute_order(self) -> dict[Any, int]:
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
        all_targets: set[FieldLike] = set()
        for dep_field, paths in triggers.items():
            for targets in paths.values():
                for target in targets:
                    if target.store and target.compute:
                        all_targets.add(target)
                        if dep_field.store and dep_field.compute:
                            all_targets.add(dep_field)

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

        queue: list[int] = [
            index for index, degree in enumerate(component_in_degree) if degree == 0
        ]
        order: dict[FieldLike, int] = {}
        priority = 0
        while queue:
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

    def freeze(self) -> None:
        state = self._state
        for field in state.triggers:
            self._tree_for(state, field)
            self._modifying_relations_for(state, field)
        if state.recompute_order is None:
            state.recompute_order = self._compute_recompute_order(state.triggers)

    def set_inverses(self, inverses: _Collector) -> None:
        self._inverses = inverses

    def set_computed(self, computed: dict[Any, list]) -> None:
        self._computed = computed

    @property
    def published_triggers(self) -> defaultdict:
        return self._state.triggers

    @property
    def field_inverses(self) -> _Collector:
        return self._inverses

    @property
    def field_depends(self) -> _Collector:
        return self._depends

    @property
    def field_depends_context(self) -> _Collector:
        return self._depends_context

    @property
    def field_computed(self) -> dict[Any, list]:
        return self._computed


def _strongly_connected_components(
    adjacency: dict[Any, set[Any]],
) -> list[list[Any]]:
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
    return field.type


def _field_attr(field: Any, attr: str) -> Any:
    return getattr(field, attr, None)


def _is_relational(field: FieldLike) -> bool:
    return field.relational
