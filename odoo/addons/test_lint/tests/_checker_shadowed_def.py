"""A method defined twice in one class body: the first one never runs.

Python keeps the last definition, so the earlier one is dead code that reads
as live. Nothing else catches it -- it is valid Python, ruff does not look
across a class body for it, and the shadowed copy usually still passes review
because the reviewer is reading *it*.

It happens for real. `stock.product_template` carried two
`_search_variant_quantity`: the live one had been written against an older
`product.product` API and called a `_get_domain_locations` that no longer
existed, so every quantity search on a product template raised AttributeError
while a correct implementation sat 60 lines above it, unreachable.

Legitimate repetitions are not findings:

* a ``@typing.overload`` stack, where every definition but the last is a
  signature declaration;
* a property group -- ``@property`` followed by ``@x.setter`` / ``@x.deleter``;
* a ``@singledispatchmethod`` and its ``@x.register`` implementations;
* definitions guarded by ``if``/``try`` (e.g. ``if TYPE_CHECKING``), which are
  alternatives rather than one overwriting the other.
"""

import ast
from collections.abc import Iterator
from dataclasses import dataclass

OVERLOAD = frozenset({"overload"})
PROPERTY = frozenset({"property", "cached_property"})
RE_DECORATED = frozenset({"setter", "deleter", "getter"})
DISPATCH = frozenset({"register", "singledispatchmethod"})


@dataclass
class Violation:
    lineno: int
    col_offset: int
    message: str


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = set()
    for decorator in node.decorator_list:
        expr = decorator.func if isinstance(decorator, ast.Call) else decorator
        while isinstance(expr, ast.Attribute):
            names.add(expr.attr)
            expr = expr.value
        if isinstance(expr, ast.Name):
            names.add(expr.id)
    return names


def _is_legitimate(definitions: list[ast.FunctionDef | ast.AsyncFunctionDef]) -> bool:
    decorators = [_decorator_names(node) for node in definitions]
    # a typing.overload stack: everything but the implementation is a signature
    if all(names & OVERLOAD for names in decorators[:-1]):
        return True
    # a property and the accessors that re-decorate it
    if decorators[0] & PROPERTY and all(
        names & RE_DECORATED for names in decorators[1:]
    ):
        return True
    # a single-dispatch method and its registrations
    return all(names & DISPATCH for names in decorators[1:])


def check(tree: ast.Module, nodes=None) -> Iterator[Violation]:
    for node in nodes if nodes is not None else ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # Only the class body itself: a definition nested in an `if` or a `try`
        # is an alternative, not a shadow.
        definitions: dict[str, list] = {}
        for statement in node.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definitions.setdefault(statement.name, []).append(statement)
        for name, found in definitions.items():
            if len(found) < 2 or _is_legitimate(found):
                continue
            shadowed = ", ".join(str(one.lineno) for one in found[:-1])
            yield Violation(
                found[-1].lineno,
                found[-1].col_offset,
                f"{node.name}.{name} is defined again here, so the definition"
                f" at line {shadowed} never runs",
            )
