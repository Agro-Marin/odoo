import ast
from collections.abc import Iterator
from dataclasses import dataclass

_MODEL_BASE_NAMES = frozenset(
    {
        "Model",
        "TransientModel",
        "AbstractModel",
        "BaseModel",
    }
)


@dataclass
class Violation:
    lineno: int
    col_offset: int
    message: str = (
        "Raise inside unlink override. Use @api.ondelete(at_uninstall=False) instead."
    )


def looks_like_model_class(node: ast.ClassDef) -> bool:
    """Shared with `_checker_translated_unique`, which carried a verbatim copy."""
    for base in node.bases:
        match base:
            case ast.Attribute(attr=attr) if attr in _MODEL_BASE_NAMES:
                return True
            case ast.Name(id=name) if name in _MODEL_BASE_NAMES:
                return True
    return False


def check(tree: ast.Module, nodes=None) -> Iterator[Violation]:
    for node in nodes if nodes is not None else ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not looks_like_model_class(node):
            continue

        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name != "unlink":
                continue

            for child in ast.walk(item):
                if isinstance(child, ast.Raise):
                    yield Violation(child.lineno, child.col_offset)
