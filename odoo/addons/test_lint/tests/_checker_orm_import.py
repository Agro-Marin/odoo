import ast
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class Violation:
    lineno: int
    col_offset: int
    message: str = ""


def _is_orm(name: str | None) -> bool:
    return bool(name) and (name == "odoo.orm" or name.startswith("odoo.orm."))


def check(tree: ast.Module, nodes=None) -> Iterator[Violation]:
    for node in nodes if nodes is not None else ast.walk(tree):
        match node:
            case ast.Import(names=names):
                for alias in names:
                    if _is_orm(alias.name):
                        yield Violation(
                            node.lineno,
                            node.col_offset,
                            f"import {alias.name}",
                        )
            case ast.ImportFrom(module=module, level=0) if _is_orm(module):
                imported = ", ".join(alias.name for alias in node.names)
                yield Violation(
                    node.lineno,
                    node.col_offset,
                    f"from {module} import {imported}",
                )
