import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass

# A name that holds a bearer secret, or a call that computes one.
TOKEN_NAME = re.compile(r"(^|_)token$")
TOKEN_CALL = re.compile(r"(_generate_\w*token|_sign_token|_encode_link\w*|^hmac)$")


@dataclass
class Violation:
    lineno: int
    col_offset: int
    message: str


def _terminal(node: ast.AST) -> tuple[str, bool]:
    if isinstance(node, ast.Call):
        name, _ = _terminal(node.func)
        return name, True
    if isinstance(node, ast.Attribute):
        return node.attr, False
    if isinstance(node, ast.Name):
        return node.id, False
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return str(node.slice.value), False
    return "", False


def _is_secret(node: ast.AST) -> bool:
    name, called = _terminal(node)
    if called:
        return bool(TOKEN_CALL.search(name))
    return bool(TOKEN_NAME.search(name))


def check(tree: ast.Module) -> Iterator[Violation]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        if not isinstance(node.ops[0], ast.Eq | ast.NotEq):
            continue
        left, right = node.left, node.comparators[0]
        if any(
            isinstance(side, ast.Constant)
            or (isinstance(side, ast.Name) and side.id.isupper())
            for side in (left, right)
        ):
            continue
        if _is_secret(left) or _is_secret(right):
            yield Violation(
                node.lineno,
                node.col_offset,
                "a token compared with `==`/`!=` leaks how many leading "
                "characters matched through the time it takes; use `consteq`",
            )
