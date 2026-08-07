"""Dynamic-domain-in-onchange checker using stdlib ``ast``.

Returning a domain from an ``@api.onchange`` method is deprecated: the domain
it produces is invisible to every other reader of the field (the server-side
``_search``, the export, a second client), so the restriction holds only for
as long as the user stays on that one form. ``domain=`` on the field, or a
computed ``Domain`` field, holds everywhere.

Extracted from ``test_onchange_domains`` so the scan that runs it can run
every other Python checker in the same pass -- see :mod:`_py_scan`.
"""

import ast
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class Violation:
    """A ``"domain"`` literal inside an ``@api.onchange`` method."""

    lineno: int
    col_offset: int
    message: str = "probable dynamic domain returned from an onchange"


def _is_onchange_decorator(node: ast.expr) -> bool:
    """Whether *node* is ``@api.onchange(...)`` / ``@onchange(...)``."""
    match node:
        case ast.Call(func=ast.Attribute(attr="onchange")):
            return True
        case ast.Call(func=ast.Name(id="onchange")):
            return True
    return False


def check(tree: ast.Module, filepath: str = "", nodes=None) -> Iterator[Violation]:
    """Yield at most one violation per ``@api.onchange`` method.

    One is enough to send someone to the method, and reporting every
    ``"domain"`` string inside a long onchange buries that.

    *nodes* is an already-materialised ``ast.walk(tree)`` shared with the other
    checkers.
    """
    for node in nodes if nodes is not None else ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(map(_is_onchange_decorator, node.decorator_list)):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and child.value == "domain":
                yield Violation(child.lineno, child.col_offset)
                break
