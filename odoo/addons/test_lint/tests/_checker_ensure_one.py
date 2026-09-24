import ast
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class Violation:
    lineno: int
    col_offset: int
    message: str


def check(tree: ast.Module) -> Iterator[Violation]:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "ensure_one"
        ):
            yield Violation(
                node.lineno,
                node.col_offset,
                "`ensure_one()` does not exist in this fork: the call raises "
                "AttributeError at runtime; use `check_singleton()`",
            )
