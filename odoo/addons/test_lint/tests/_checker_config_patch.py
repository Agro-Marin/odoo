import ast
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class Violation:
    lineno: int
    col_offset: int
    message: str = ""


def _is_patch_dict(func: ast.expr) -> bool:
    match func:
        case ast.Attribute(attr="dict", value=ast.Name(id="patch")):
            return True
        case ast.Attribute(attr="dict", value=ast.Attribute(attr="patch")):
            return True
    return False


def _is_config_options(node: ast.expr) -> bool:
    match node:
        case ast.Attribute(attr="options", value=ast.Name(id="config")):
            return True
        case ast.Attribute(attr="options", value=ast.Attribute(attr="config")):
            return True
    return False


def check(tree: ast.Module, nodes=None) -> Iterator[Violation]:
    for node in nodes if nodes is not None else ast.walk(tree):
        match node:
            case ast.Call(func=func, args=[first, *_]) if _is_patch_dict(
                func
            ) and _is_config_options(first):
                yield Violation(
                    node.lineno,
                    node.col_offset,
                    "use config.patch(**values) — patch.dict flattens the "
                    "options ChainMap into _override_options",
                )
