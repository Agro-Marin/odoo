"""N+1 query pattern checker using stdlib ``ast``.

Detects ORM query methods (``search``, ``search_count``, ``search_fetch``,
``_read_group``) called inside ``for`` loop bodies.  These are almost always
N+1 anti-patterns — the query should be hoisted before the loop and the
results filtered or indexed in memory.

Example of flagged code::

    for record in records:
        partners = self.env["res.partner"].search([("id", "=", record.partner_id.id)])

Correct alternative::

    partners = self.env["res.partner"].search(
        [("id", "in", records.mapped("partner_id").ids)]
    )
    for record in records:
        partner = partners.filtered(lambda p: p.id == record.partner_id.id)
"""

import ast
from collections.abc import Iterator
from dataclasses import dataclass

# ORM methods that execute a database query per call.
_QUERY_METHODS = frozenset(
    {
        "search",
        "search_count",
        "search_fetch",
        "_read_group",
    }
)


@dataclass(slots=True)
class Violation:
    """A single N+1 query warning."""

    lineno: int
    col_offset: int
    message: str


def _is_query_call(node: ast.Call) -> str | None:
    """Return the method name if *node* is an ORM query call, else ``None``.

    Matches patterns like ``self.env['model'].search(...)``,
    ``records.search(...)``, ``self.search(...)``.

    Excludes non-ORM calls like ``re.search()``, ``REGEX.search()``,
    ``pattern.search()``.
    """
    match node.func:
        case ast.Attribute(attr=attr) if attr in _QUERY_METHODS:
            if attr != "search" or _looks_like_orm_receiver(node.func.value):
                return attr
    return None


def _looks_like_orm_receiver(node: ast.expr) -> bool:
    """Return True if *node* looks like an ORM recordset expression.

    Rejects patterns that are clearly not ORM:
    - ``re.search(...)`` — stdlib module
    - ``CONSTANT.search(...)`` — compiled regex (ALL_CAPS name)
    - ``pattern.search(...)`` — bare name that could be a regex variable

    Accepts patterns that are clearly ORM:
    - ``self.search(...)`` / ``self.env[...].search(...)``
    - ``Model.search(...)`` where Model is CamelCase
    - ``records.search(...)`` via attribute chain (``obj.field.search``)
    """
    match node:
        # self.search() or self.env['model'].search()
        case ast.Name(id="self"):
            return True
        # self.env[...].search(), self.sudo().search(), etc.
        case ast.Attribute():
            return _has_self_root(node)
        # env['model'].search() via subscript
        case ast.Subscript():
            return _has_self_root(node)
        # Model.search() — CamelCase class name
        case ast.Name(id=name) if name[0].isupper() and not name.isupper():
            return True
        # Anything called on a function result: some_func().search()
        case ast.Call():
            return True
    return False


def _has_self_root(node: ast.expr) -> bool:
    """Return True if the leftmost name in an attribute/subscript chain is ``self``."""
    match node:
        case ast.Name(id="self"):
            return True
        case ast.Attribute(value=value):
            return _has_self_root(value)
        case ast.Subscript(value=value):
            return _has_self_root(value)
        case ast.Call(func=func):
            return _has_self_root(func)
    return False


def check(tree: ast.Module, filepath: str = "") -> Iterator[Violation]:
    """Walk *tree* and yield N+1 query violations.

    Skips test files and test directories since test code often uses loops
    for readability over performance.
    """
    if filepath and (
        filepath.rsplit("/", 1)[-1].startswith("test_") or "/tests/" in filepath
    ):
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            # Walk only the loop body, not the iterable expression
            for stmt in node.body:
                yield from _walk_for_queries_in_subtree(stmt)
            for stmt in node.orelse:
                yield from _walk_for_queries_in_subtree(stmt)


def _walk_for_queries_in_subtree(node: ast.AST) -> Iterator[Violation]:
    """Yield violations for ORM query calls anywhere in *node*'s subtree.

    Skips nested function/class definitions (new scopes) — queries inside
    those execute when called, not per-iteration of the outer loop.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return

    if isinstance(node, ast.Call):
        method_name = _is_query_call(node)
        if method_name is not None:
            yield Violation(
                lineno=node.lineno,
                col_offset=node.col_offset,
                message=(
                    f"ORM query '{method_name}()' inside for loop — "
                    f"potential N+1 pattern. Hoist the query before the loop."
                ),
            )

    for child in ast.iter_child_nodes(node):
        yield from _walk_for_queries_in_subtree(child)
