from __future__ import annotations

from collections.abc import Sequence

__all__ = ["get_trigger_trees"]

Bucket = tuple[Sequence[int], Sequence[int]]
Meta = tuple[bool, bool, int, int, int, int]
Node = tuple[list[int], list[tuple[int, "Node"]]]


def _cancels(meta: Sequence[Meta], f1: int, f2: int) -> bool:
    a_m2o, _, a_name, _, a_model, a_comodel = meta[f1]
    _, b_o2m, _, b_inverse, b_model, b_comodel = meta[f2]
    return (
        a_m2o
        and b_o2m
        and b_inverse == a_name
        and a_model == b_comodel
        and a_comodel == b_model
    )


def _concat_paths(
    meta: Sequence[Meta], prefix: tuple[int, ...], path: Sequence[int]
) -> tuple[int, ...]:
    left, right = prefix, tuple(path)
    while left and right and _cancels(meta, left[-1], right[0]):
        left, right = left[:-1], right[1:]
    return left + right


def _get_tree(
    triggers: dict[int, Sequence[Bucket]], meta: Sequence[Meta], field: int
) -> Node:
    if field not in triggers:
        return ([], [])
    collected: dict[tuple[int, ...], tuple[list[int], set[int]]] = {}
    seen: set[int] = set()
    expanded: set[tuple[int, tuple[int, ...]]] = set()
    visited_memo: dict[int, frozenset[int]] = {}

    def collect(field: int, prefix: tuple[int, ...]) -> frozenset[int] | None:
        if (field, prefix) in expanded:
            visited = visited_memo[field]
            if visited.isdisjoint(seen):
                return visited
        seen.add(field)
        visited = frozenset({field})
        clean = True
        for path, targets in triggers[field]:
            full_path = _concat_paths(meta, prefix, path)
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
            visited_memo[field] = visited
            expanded.add((field, prefix))
            return visited
        return None

    collect(field, ())

    tree: Node = ([], [])
    for full_path, (root_list, _root_set) in collected.items():
        current = tree
        for label in full_path:
            for child_label, child in current[1]:
                if child_label == label:
                    current = child
                    break
            else:
                child = ([], [])
                current[1].append((label, child))
                current = child
        current[0].extend(root_list)
    return tree


def get_trigger_trees(
    triggers: Sequence[tuple[int, Sequence[Bucket]]],
    meta: Sequence[Meta],
    fields: Sequence[int] | None = None,
) -> list[tuple[int, Node]]:
    by_field = dict(triggers)
    if fields is None:
        fields = list(by_field)
    n = len(meta)
    for dep, buckets in by_field.items():
        if dep >= n or any(
            f >= n for path, targets in buckets for f in (*path, *targets)
        ):
            raise IndexError("get_trigger_trees: a field id is out of range of `meta`")
    if any(f >= n for f in fields):
        raise IndexError("get_trigger_trees: a field id is out of range of `meta`")
    return [(field, _get_tree(by_field, meta, field)) for field in fields]
