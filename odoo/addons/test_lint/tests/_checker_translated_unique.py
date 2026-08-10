"""Detect UNIQUE rules declared over a translated column.

A ``translate=True`` field is stored as ``jsonb``, so a UNIQUE over it compares
whole translation *documents* rather than values. Two rows stop colliding the
moment one carries a language the other does not -- which is the next create in
a second language, not some later translation step, because Odoo writes the
active language alongside the source term. The rule silently enforces nothing
from then on.

The fix is an expression index over the source term, ``name_uniq_index()`` in
``odoo/addons/base/models/catalog_mixin.py``.

This cannot be a per-file checker. Whether a column is translated is often
decided somewhere else: on another module's extension of the same model, or on
a mixin the model inherits. The detector therefore takes the whole tree at once
and resolves ``_inherit`` before judging any constraint.
"""

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

_MODEL_BASES = frozenset({"Model", "TransientModel", "AbstractModel", "BaseModel"})

# `unique (a, b)` / `UNIQUE NULLS NOT DISTINCT (a, b)`, anywhere in the text
_UNIQUE_COLUMNS = re.compile(
    r"unique\s*(?:nulls\s+not\s+distinct\s*)?\(([^)]*)\)", re.IGNORECASE
)
# a UniqueIndex definition leads with its column list: `(a, b) WHERE ...`
_INDEX_COLUMNS = re.compile(r"^\s*\(([^)]*)\)")
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*", re.IGNORECASE)


@dataclass
class ClassInfo:
    """What one `class Foo(models.Model)` contributes about its model."""

    model: str
    parents: tuple[str, ...] = ()
    translated: set[str] = field(default_factory=set)
    # (attribute name, sql text, lineno, is_index)
    rules: list[tuple[str, str, int, bool]] = field(default_factory=list)


@dataclass(frozen=True)
class Violation:
    path: str
    lineno: int
    model: str
    attribute: str
    columns: tuple[str, ...]
    rule: str = "unique-over-translated-column"

    def __str__(self) -> str:
        cols = ", ".join(self.columns)
        return (
            f"{self.path}:{self.lineno} [{self.rule}] {self.model}.{self.attribute} "
            f"is UNIQUE over translated column(s) {cols}; it compares jsonb "
            f"documents, not values -- use name_uniq_index()"
        )


def _literal(node: ast.AST):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _str_or_list(node: ast.AST) -> tuple[str, ...]:
    value = _literal(node)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(v for v in value if isinstance(v, str))
    return ()


def _looks_like_model(node: ast.ClassDef) -> bool:
    for base in node.bases:
        match base:
            case ast.Attribute(attr=attr) if attr in _MODEL_BASES:
                return True
            case ast.Name(id=name) if name in _MODEL_BASES:
                return True
    return False


def _is_translated_field(call: ast.Call) -> bool:
    func = call.func
    if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
        return False
    if func.value.id != "fields":
        return False
    for keyword in call.keywords:
        if keyword.arg == "translate" and _literal(keyword.value) is True:
            return True
    return False


def collect(tree: ast.Module) -> list[ClassInfo]:
    """Everything one parsed file says about the models it defines or extends."""
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and _looks_like_model(node)):
            continue
        names: tuple[str, ...] = ()
        inherits: tuple[str, ...] = ()
        translated: set[str] = set()
        rules: list[tuple[str, str, int, bool]] = []
        for stmt in node.body:
            if not (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
            ):
                continue
            key = stmt.targets[0].id
            value = stmt.value
            if key == "_name":
                names = _str_or_list(value)
            elif key == "_inherit":
                inherits = _str_or_list(value)
            elif key == "_sql_constraints":
                rules.extend(
                    (str(row[0]), str(row[1]), stmt.lineno, False)
                    for row in _literal(value) or ()
                    if isinstance(row, (list, tuple)) and len(row) > 1
                )
            elif isinstance(value, ast.Call):
                func = value.func
                attr = func.attr if isinstance(func, ast.Attribute) else None
                if attr in ("Constraint", "UniqueIndex") and value.args:
                    text = _literal(value.args[0])
                    if isinstance(text, str):
                        rules.append((key, text, stmt.lineno, attr == "UniqueIndex"))
                elif not key.startswith("_") and _is_translated_field(value):
                    translated.add(key)

        model = names[0] if names else (inherits[0] if inherits else None)
        if not model:
            continue
        parents = tuple(p for p in inherits if p != model) if names else ()
        out.append(ClassInfo(model, parents, translated, rules))
    return out


def resolve_translated(infos: list[ClassInfo]) -> dict[str, set[str]]:
    """Translated fields per model, following ``_inherit`` to its fixed point.

    A model's own declarations are merged with every parent's, transitively --
    a constraint on a concrete model is just as broken when the column it names
    was declared ``translate=True`` by a mixin two levels up.
    """
    own: dict[str, set[str]] = {}
    parents: dict[str, set[str]] = {}
    for info in infos:
        own.setdefault(info.model, set()).update(info.translated)
        parents.setdefault(info.model, set()).update(info.parents)

    resolved: dict[str, set[str]] = {}

    def walk(model: str, seen: frozenset[str]) -> set[str]:
        if model in resolved:
            return resolved[model]
        if model in seen:  # _inherit cycles are legal enough to survive
            return set()
        fields_ = set(own.get(model, ()))
        for parent in parents.get(model, ()):
            fields_ |= walk(parent, seen | {model})
        if not (seen & parents.get(model, set())):
            resolved[model] = fields_
        return fields_

    for model in own:
        walk(model, frozenset())
    return resolved


def _columns(text: str, is_index: bool) -> tuple[str, ...]:
    match = (_INDEX_COLUMNS if is_index else _UNIQUE_COLUMNS).search(text)
    if not match:
        return ()
    return tuple(
        token.strip().strip('"').strip("'") for token in match.group(1).split(",")
    )


def violations(units: list[tuple[str, list[ClassInfo]]]) -> Iterator[Violation]:
    """Flag every UNIQUE rule naming a column that is translated.

    A definition already going through ``->>`` is the fixed form and is left
    alone; so is a column list that names nothing translated.
    """
    translated = resolve_translated([info for _path, infos in units for info in infos])
    for path, infos in units:
        for info in infos:
            model_fields = translated.get(info.model, set())
            if not model_fields:
                continue
            lowered = {name.lower() for name in model_fields}
            for attribute, text, lineno, is_index in info.rules:
                if "->>" in text:
                    continue
                if not is_index and not _UNIQUE_COLUMNS.search(text):
                    continue
                columns = _columns(text, is_index)
                if is_index:
                    # a partial index carries a predicate; only the key matters
                    columns = tuple(
                        token
                        for column in columns
                        for token in _IDENTIFIER.findall(column)
                    )
                hit = tuple(c for c in columns if c.lower() in lowered)
                if hit:
                    yield Violation(path, lineno, info.model, attribute, hit)
