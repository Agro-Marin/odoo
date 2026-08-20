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
    """The imports that exist for a type checker and never execute.

    The facade rule is about what an addon *runs*. `coding_guidelines.rst` §2.1
    and `doc/adr/0008-enforce-facade-boundary.md` allow `odoo.orm` under
    `if TYPE_CHECKING:` precisely so a module can annotate a `Query` or a
    `DomainType` without taking a runtime dependency on the ORM, and
    `tooling/architecture/layer_check.py` -- the same rule enforced over the
    core -- skips those blocks for that reason. This checker did not, so one
    rule had two answers, and the guarded form the guidelines recommend was the
    one it flagged.

    Only the block's `body` is exempt: an `else:` under `if TYPE_CHECKING:`, or
    an `if not TYPE_CHECKING:`, is the branch that does run.
    """
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking_test(node.test):
            for statement in node.body:
                for child in ast.walk(statement):
                    if isinstance(child, (ast.Import, ast.ImportFrom)):
                        guarded.add(id(child))
    return guarded


def check(tree: ast.Module, nodes=None) -> Iterator[Violation]:
    # `id()` is exact here and cheap: `nodes`, when given, is a walk of this
    # same tree, which stays alive for the call.
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
