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


def _is_domain_mapping(node: ast.AST) -> bool:
    """A ``{'domain': ...}`` mapping -- the shape an onchange actually returns.

    The rule used to fire on *any* string constant equal to ``"domain"``
    anywhere in the method, so a search on a field named `domain`
    (``[('domain', '=', self.domain)]``) read as a dynamic domain. Only a
    mapping key can be the one an onchange returns.
    """
    return isinstance(node, ast.Dict) and any(
        isinstance(key, ast.Constant) and key.value == "domain" for key in node.keys
    )


def check(tree: ast.Module, nodes=None) -> Iterator[Violation]:
    for node in nodes if nodes is not None else ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(map(_is_onchange_decorator, node.decorator_list)):
            continue
        for child in ast.walk(node):
            if _is_domain_mapping(child):
                yield Violation(child.lineno, child.col_offset)
                break
