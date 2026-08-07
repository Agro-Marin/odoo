"""Direct-``odoo.orm``-import checker.

Addon runtime code must reach the ORM through the public facade (``odoo.api``,
``odoo.fields``, ``odoo.models``), never by importing the unstable internal
``odoo.orm`` package.

Test files are exempt *by location*. Testing an ORM internal necessarily
imports it, and tests are not shipped API surface, so they carry none of the
version-drift risk this guard exists to prevent -- that exemption is the sole
reason the previous per-module allow-list (``base``, ``test_orm``,
``test_performance``) existed. Skipping tests by path instead of naming modules
keeps the check self-maintaining and, unlike the allow-list, still enforces the
rule on every module's runtime code, ``base`` included.

Operates on the AST rather than a line regex so that ``odoo.orm`` inside a
string or a comment is not a finding, and so the report can name the imported
symbol.
"""

import ast
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class Violation:
    """An import reaching into the internal ``odoo.orm`` package."""

    lineno: int
    col_offset: int
    message: str = ""


def _is_orm(name: str | None) -> bool:
    return bool(name) and (name == "odoo.orm" or name.startswith("odoo.orm."))


def check(tree: ast.Module, filepath: str = "", nodes=None) -> Iterator[Violation]:
    """Yield a violation per ``import odoo.orm...`` / ``from odoo.orm... import``.

    Files under a ``tests`` directory are skipped; see the module docstring.

    *nodes* is an already-materialised ``ast.walk(tree)`` shared with the other
    checkers.
    """
    if "/tests/" in filepath or filepath.endswith("/tests"):
        return

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
