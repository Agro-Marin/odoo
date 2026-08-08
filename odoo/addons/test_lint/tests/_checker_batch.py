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
    # Only `search` is gated on the receiver, and that asymmetry is deliberate.
    # The gate exists for one reason: `re.search`, `PATTERN.search` and
    # `<compiled>.search` share the name, and a regex in a loop is not an N+1.
    # No such collision exists for `search_count`, `search_fetch` or
    # `_read_group`, and `_looks_like_orm_receiver` cannot recognise a plain
    # recordset variable -- `record`, `session`, `move.move_line_ids` all fail
    # it. Extending the gate to the other three therefore buys nothing and
    # costs 10 true findings, which is measured, not assumed.
    match node.func:
        case ast.Attribute(attr=attr, value=receiver) if attr in _QUERY_METHODS:
            if attr != "search" or _looks_like_orm_receiver(receiver):
                return attr
    return None


def _looks_like_orm_receiver(node: ast.expr) -> bool:
    match node:
        # `<anything>.env[...]` is a recordset whatever the chain is rooted at.
        # Requiring a `self` root missed `for rec in recs: rec.env['x'].search(...)`
        # -- the single most idiomatic shape this rule exists to catch -- in 14
        # places, while `search_count` caught the same shape only because it
        # skipped the receiver test entirely.
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
    # `async for` counts. It iterates and runs its body per item exactly as
    # `for` does, so a query in it is the same N+1 -- the rule just could not
    # see it, because `ast.AsyncFor` is a separate node type. (`while` is
    # excluded on purpose: it is an iterate-until-done shape, not a
    # record-by-record one.)
    #
    # The `else:` clause is not scanned. It runs once, after the loop, exactly
    # like the statement following it -- a query there is not per-record and
    # never was. Neither is `iter`, for the same reason.
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
