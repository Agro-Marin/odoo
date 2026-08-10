__all__ = ["merge_sequences", "topological_sort"]

from collections import defaultdict
from typing import TYPE_CHECKING, cast

from .sentinel import SENTINEL, Sentinel

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator, Mapping


def topological_sort[T](
    elems: Mapping[T, Collection[T]], *, strict: bool = True
) -> list[T]:
    result: list[T] = []
    visited: set[T] = set()
    path: set[T] = set()

    for root in elems:
        if root in visited:
            continue
        visited.add(root)
        path.add(root)
        stack: list[tuple[T, Iterator[T]]] = [(root, iter(elems[root]))]
        while stack:
            node, deps = stack[-1]
            for dep in deps:
                if dep == node:
                    continue
                if dep in path:
                    if strict:
                        raise ValueError(
                            f"topological_sort: cyclic dependency involving {dep!r}"
                        )
                    continue
                if dep in visited:
                    continue
                visited.add(dep)
                if dep in elems:
                    path.add(dep)
                    stack.append((dep, iter(elems[dep])))
                    break
            else:
                stack.pop()
                path.discard(node)
                result.append(node)

    return result


def merge_sequences[T](*iterables: Iterable[T]) -> list[T]:
    deps: defaultdict[T, list[T]] = defaultdict(list)
    for iterable in iterables:
        prev: T | Sentinel = SENTINEL
        for item in iterable:
            if prev is SENTINEL:
                deps[item]
            else:
                deps[item].append(cast("T", prev))
            prev = item
    return topological_sort(deps, strict=False)
