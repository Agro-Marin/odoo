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


def check(tree: ast.Module, filepath: str = "") -> Iterator[Violation]:
    if filepath and (
        filepath.rsplit("/", 1)[-1].startswith("test_") or "/tests/" in filepath
    ):
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            for stmt in node.body:
                yield from _walk_for_queries_in_subtree(stmt)
            for stmt in node.orelse:
                yield from _walk_for_queries_in_subtree(stmt)


def _walk_for_queries_in_subtree(node: ast.AST) -> Iterator[Violation]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return

    if isinstance(node, ast.Call):
        method_name = _is_query_call(node)
        if method_name is not None:
            yield Violation(
                lineno=node.lineno,
                col_offset=node.col_offset,
                message=(
                    f"ORM query '{method_name}()' inside for loop — "
                    f"potential N+1 pattern. Hoist the query before the loop."
                ),
            )

    for child in ast.iter_child_nodes(node):
        yield from _walk_for_queries_in_subtree(child)
