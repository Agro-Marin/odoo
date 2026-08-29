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


def _is_type_checking_test(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _type_checking_imports(tree: ast.Module) -> set[int]:
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking_test(node.test):
            for statement in node.body:
                for child in ast.walk(statement):
                    if isinstance(child, (ast.Import, ast.ImportFrom)):
                        guarded.add(id(child))
    return guarded


def check(tree: ast.Module, nodes=None) -> Iterator[Violation]:
    guarded = _type_checking_imports(tree)
    for node in nodes if nodes is not None else ast.walk(tree):
        if id(node) in guarded:
            continue
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
