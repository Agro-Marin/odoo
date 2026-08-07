import ast
from collections.abc import Iterator
from dataclasses import dataclass

_QUERY_METHODS = frozenset(
    {
        "search",
        "search_count",
        "search_fetch",
        "_read_group",
    }
)


@dataclass(slots=True)
class Violation:
    lineno: int
    col_offset: int
    message: str


def _is_query_call(node: ast.Call) -> str | None:
    match node.func:
        case ast.Attribute(attr=attr) if attr in _QUERY_METHODS:
            if attr != "search" or _looks_like_orm_receiver(node.func.value):
                return attr
    return None


def _looks_like_orm_receiver(node: ast.expr) -> bool:
    match node:
        case ast.Name(id="self"):
            return True
        case ast.Attribute():
            return _has_self_root(node)
        case ast.Subscript():
            return _has_self_root(node)
        case ast.Name(id=name) if name[0].isupper() and not name.isupper():
            return True
        case ast.Call():
            return True
    return False


def _has_self_root(node: ast.expr) -> bool:
    match node:
        case ast.Name(id="self"):
            return True
        case ast.Attribute(value=value):
            return _has_self_root(value)
        case ast.Subscript(value=value):
            return _has_self_root(value)
        case ast.Call(func=func):
            return _has_self_root(func)
    return False


def check(tree: ast.Module, filepath: str = "", nodes=None) -> Iterator[Violation]:
    """Walk *tree* and yield N+1 query violations.

    Skips test files and test directories since test code often uses loops
    for readability over performance.

    Only the **outermost** ``for`` of a nest is used as the entry point. Every
    ``for`` used to be its own entry, and since the subtree walk descends into
    nested loops, one query in a doubly-nested loop was reported twice and in a
    triply-nested loop three times -- the count grew with the indentation rather
    than with the defect.

    *nodes* is an already-materialised ``ast.walk(tree)`` shared with the other
    checkers.
    """
    if filepath and (
        filepath.rsplit("/", 1)[-1].startswith("test_") or "/tests/" in filepath
    ):
        return iter(())

    # `ast.walk` is breadth-first, so an enclosing `for` is always seen before
    # the ones nested in it. Marking the nested ones as we descend therefore
    # costs one set insertion, and needs no second traversal to find them.
    nested: set[int] = set()
    violations: list[Violation] = []
    for node in nodes if nodes is not None else ast.walk(tree):
        if not isinstance(node, ast.For) or id(node) in nested:
            continue
        for stmt in (*node.body, *node.orelse):
            _collect(stmt, nested, violations)
    return iter(violations)


def _collect(node: ast.AST, nested: set[int], out: list[Violation]) -> None:
    """Record ORM query calls anywhere in *node*'s subtree.

    Skips nested function/class definitions **and lambdas** — all three create a
    scope whose body runs when called, not once per iteration of the enclosing
    loop. The lambda was previously flagged while the equivalent ``def`` was
    not, so the same deferred query was or was not an N+1 depending on which
    syntax expressed it.

    Nested ``for`` nodes are recorded in *nested* on the way past, so the caller
    does not use them as entry points of their own.
    """
    if isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    ):
        return

    if isinstance(node, ast.For):
        nested.add(id(node))
    elif isinstance(node, ast.Call):
        method_name = _is_query_call(node)
        if method_name is not None:
            out.append(
                Violation(
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    message=(
                        f"ORM query '{method_name}()' inside for loop — "
                        f"potential N+1 pattern. Hoist the query before the loop."
                    ),
                )
            )

    for child in ast.iter_child_nodes(node):
        _collect(child, nested, out)
