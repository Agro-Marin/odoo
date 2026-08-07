import ast
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class Violation:
    lineno: int
    col_offset: int
    message: str = "probable dynamic domain returned from an onchange"


def _is_onchange_decorator(node: ast.expr) -> bool:
    match node:
        case ast.Call(func=ast.Attribute(attr="onchange")):
            return True
        case ast.Call(func=ast.Name(id="onchange")):
            return True
    return False


def check(tree: ast.Module, nodes=None) -> Iterator[Violation]:
    for node in nodes if nodes is not None else ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(map(_is_onchange_decorator, node.decorator_list)):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and child.value == "domain":
                yield Violation(child.lineno, child.col_offset)
                break
