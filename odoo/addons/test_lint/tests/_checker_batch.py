import ast
from collections.abc import Iterator
from dataclasses import dataclass

# Judged against the tree, not guessed. `search_read` and `name_search` add 12
# findings and lose none, and every one of the twelve is a `for x in <records>:`
# with a query inside. What is deliberately NOT here:
#
#   read          42 findings, dominated by `file.read()` and `self.device.read()`
#   read_group    0 -- the method is `_read_group` in 19.0
#   _search       15, mostly loops over a handful of domains rather than records
#
# The loop set is `for`/`async for` for the same reason: treating `while` as a
# loop adds 13 findings, and all of them are worklist or paging loops issuing one
# BATCHED query per iteration (`Lot.search(name in candidates)`), not one per
# record. Comprehensions add 4, every one a short-circuiting `any(...)`.
_QUERY_METHODS = frozenset(
    {
        "search",
        "search_count",
        "search_fetch",
        "search_read",
        "name_search",
        "_read_group",
    }
)

_RECORDSET_METHODS = frozenset(
    {
        "sudo",
        "with_context",
        "with_user",
        "with_company",
        "with_env",
        "browse",
        "exists",
        "filtered",
        "filtered_domain",
        "mapped",
        "sorted",
        "union",
        "concat",
    }
)


@dataclass(slots=True)
class Violation:
    lineno: int
    col_offset: int
    message: str


def _is_query_call(node: ast.Call) -> str | None:
    match node.func:
        case ast.Attribute(attr=attr, value=receiver) if attr in _QUERY_METHODS:
            if attr != "search" or _looks_like_orm_receiver(receiver):
                return attr
    return None


def _looks_like_orm_receiver(node: ast.expr) -> bool:
    match node:
        case ast.Subscript(value=ast.Attribute(attr="env")):
            return True
        case ast.Name(id="self"):
            return True
        case ast.Attribute():
            return _has_self_root(node)
        case ast.Subscript():
            return _has_self_root(node)
        case ast.Name(id=name) if name[0].isupper() and not name.isupper():
            return True
        case ast.Call(func=ast.Attribute(attr=attr, value=receiver)):
            return attr in _RECORDSET_METHODS or _looks_like_orm_receiver(receiver)
        case ast.Call():
            return False
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


def check(tree: ast.Module, nodes=None) -> Iterator[Violation]:
    nested: set[int] = set()
    violations: list[Violation] = []
    for node in nodes if nodes is not None else ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor)) or id(node) in nested:
            continue
        for stmt in node.body:
            _collect(stmt, nested, violations)
    return iter(violations)


def _collect(node: ast.AST, nested: set[int], out: list[Violation]) -> None:
    if isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    ):
        return

    if isinstance(node, (ast.For, ast.AsyncFor)):
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
