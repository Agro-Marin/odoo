"""Sequence merging and topological sorting helpers."""

__all__ = ["merge_sequences", "topological_sort"]

from collections import defaultdict
from typing import TYPE_CHECKING

from .sentinel import SENTINEL, Sentinel

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator, Mapping


def topological_sort[T](
    elems: Mapping[T, Collection[T]], *, strict: bool = True
) -> list[T]:
    """Return the elements sorted so that each one's dependencies precede it.

    :param elems: specifies the elements to sort with their dependencies; it is
        a dictionary like `{element: dependencies}` where `dependencies` is a
        collection of elements that must appear before `element`. The elements
        of `dependencies` are not required to appear in `elems`; they will
        simply not appear in the result.
    :param strict: what to do when the dependencies contain a cycle. ``True``
        (the default) raises, because for a real dependency graph — module
        ``depends``, asset bundles — a cycle is a data error that a silently
        wrong order only hides. ``False`` restores the historical behaviour:
        the back-edge closing the cycle is dropped and the sort continues, for
        callers whose input is a *best-effort* merge of partial orders where
        conflicts are expected rather than exceptional (see
        :func:`merge_sequences`).

    :returns: a list with the keys of `elems` sorted according to their
        specification.
    :raises ValueError: if ``strict`` and the dependencies contain a cycle of
        two or more elements, which makes the ordering contract unsatisfiable.
        A self-edge (``{a: [a]}``) is degenerate rather than contradictory and
        is ignored either way.
    """
    # The algorithm is inspired by [Tarjan 1976],
    # http://en.wikipedia.org/wiki/Topological_sorting#Algorithms
    #
    # Iterative rather than recursive: a recursive DFS blew the interpreter
    # stack on long dependency chains (RecursionError past ~1k links), and a
    # dependency chain is attacker-/data-shaped, not bounded by the code.
    #
    # ``path`` tracks the nodes on the current DFS branch so a cycle is
    # reported instead of silently yielding an order that violates the very
    # contract this function exists to guarantee.
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
                    # Degenerate self-edge, not an ordering conflict. Real data
                    # relies on it: a manifest without "depends" defaults to
                    # ["base"], so the base module depends on itself
                    # (ir_asset._topological_sort).
                    continue
                if dep in path:
                    if strict:
                        raise ValueError(
                            f"topological_sort: cyclic dependency involving {dep!r}"
                        )
                    # Non-strict: drop the back-edge and carry on. ``dep`` is an
                    # ancestor on the current branch, so it is already scheduled
                    # to be emitted after ``node`` — exactly what the recursive
                    # implementation did by short-circuiting on ``visited``.
                    continue
                if dep in visited:
                    continue
                visited.add(dep)
                if dep in elems:
                    path.add(dep)
                    stack.append((dep, iter(elems[dep])))
                    break  # descend into dep, resume this iterator later
                # a dependency absent from elems is never emitted
            else:
                # every dependency of node has been emitted
                stack.pop()
                path.discard(node)
                result.append(node)

    return result


def merge_sequences[T](*iterables: Iterable[T]) -> list[T]:
    """Merge several iterables into a list.

    The result is the union of the iterables, ordered following the partial
    order given by the iterables, with a bias towards the end for the last
    iterable::

        seq = merge_sequences(["A", "B", "C"])
        assert seq == ["A", "B", "C"]

        seq = merge_sequences(
            ["A", "B", "C"],
            ["Z"],  # 'Z' can be anywhere
            ["Y", "C"],  # 'Y' must precede 'C';
            ["A", "X", "Y"],  # 'X' must follow 'A' and precede 'Y'
        )
        assert seq == ["A", "B", "X", "Y", "C", "Z"]

    Contradictory inputs (``["a", "b"]`` and ``["b", "a"]``) are resolved rather
    than rejected: this merges *partial* orders, so a conflict is an ordinary
    outcome, not a data error.

    .. warning::

        Which of the contradictory constraints survives is **unspecified**.  The
        result is deterministic for a given input -- the same arguments always
        produce the same list -- but it is decided by which edge happens to close
        a cycle during the depth-first walk, not by the order the sequences were
        passed in.  In particular it is *not* "the first sequence wins", as this
        docstring used to claim: ``merge_sequences(["a", "b"], ["b", "a"])``
        returns ``["b", "a"]``, and ``merge_sequences(["b", "a"], ["a", "b"])``
        returns ``["a", "b"]`` -- in both cases the *second* argument's order is
        the one that holds.  Do not build on it either way.

    It has to stay that way —
    ``Selection._setup`` merges a base ``selection`` with each module's
    ``selection_add`` through here while building the registry, and a module
    reordering existing values must not take the server down. Hence
    ``strict=False``; contrast :func:`topological_sort`, whose own callers pass
    real dependency graphs where a cycle is a genuine error.
    """
    # dict is ordered
    deps: defaultdict[T, list[T]] = defaultdict(list)  # {item: elems_before_item}
    for iterable in iterables:
        prev: T | Sentinel = SENTINEL
        for item in iterable:
            if prev is SENTINEL:
                deps[item]  # just set the default
            else:
                deps[item].append(prev)  # type: ignore[arg-type]
            prev = item
    return topological_sort(deps, strict=False)
