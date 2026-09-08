import ast
from collections.abc import Iterator
from dataclasses import dataclass

ROW_COUNTER = "sql_log_count"


@dataclass
class Violation:
    lineno: int
    col_offset: int
    message: str = "sql_log_count counts rows, not round trips"


def check(tree: ast.Module, nodes=None) -> Iterator[Violation]:
    for node in nodes if nodes is not None else ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr != ROW_COUNTER:
            continue
        if isinstance(node.ctx, ast.Store):
            continue
        yield Violation(node.lineno, node.col_offset)
