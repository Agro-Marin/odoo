"""A composite UNIQUE that says nothing about its nullable member.

PostgreSQL treats NULLs as distinct in a unique index unless the constraint
says NULLS NOT DISTINCT, so ``UNIQUE (a, b)`` enforces nothing at all on the
rows where ``b`` is empty. A constraint whose name says it holds the model's
key therefore does not hold it for a reachable subset, and nothing reports
that -- it is the CHECK a NULL satisfies, one constraint family over.

Both intents are legitimate and this fork can spell both, so the finding is
the SILENCE rather than either choice:

* the key must hold even when the column is empty -- say NULLS NOT DISTINCT;
* the empty rows are deliberately exempt -- say ``WHERE <column> IS NOT NULL``,
  which is what a plain UNIQUE was already doing, and now says so.

Only COMPOSITE constraints are reported. A single-column ``UNIQUE (imei)`` on
an optional identifier is the common and correct idiom -- NULL means "not set"
and repeated unset rows are intended -- so flagging it would bank a correct
construct as debt, which is the mistake the CHECK-constraint family teaches.
In a composite key the same silence is a defect instead: one empty column
excuses the whole tuple.

Nullability is resolved per MODEL, not per file: Odoo makes a column NOT NULL
when any declaration of the field says ``required=True``, so a bridge module
can settle it for a model whose constraint lives elsewhere. A column this scan
never sees declared is left alone rather than guessed at.
"""

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from ._checker_unlink import looks_like_model_class

_UNIQUE_COLUMNS = re.compile(
    r"unique\s*(?:nulls\s+not\s+distinct\s*)?\(([^)]*)\)", re.IGNORECASE
)
_NULLS_NOT_DISTINCT = re.compile(r"nulls\s+not\s+distinct", re.IGNORECASE)
_PARTIAL = re.compile(r"\bwhere\b", re.IGNORECASE)
_BARE_COLUMN = re.compile(r"[a-z_][a-z0-9_]*", re.IGNORECASE)

RULE = "null-exempt-composite-unique"


@dataclass
class ClassInfo:
    model: str
    parents: tuple[str, ...] = ()
    required: dict[str, bool] = field(default_factory=dict)
    rules: list[tuple[str, str, int, bool]] = field(default_factory=list)


@dataclass(frozen=True)
class Violation:
    path: str
    lineno: int
    model: str
    attribute: str
    columns: tuple[str, ...]
    nullable: tuple[str, ...]
    rule: str = RULE

    def __str__(self) -> str:
        empty = ", ".join(self.nullable)
        cols = ", ".join(self.columns)
        return (
            f"{self.path}:{self.lineno} [{self.rule}] {self.model}.{self.attribute} "
            f"is UNIQUE ({cols}), and {empty} may be NULL; PostgreSQL exempts those "
            f"rows, so the key does not hold for them -- say NULLS NOT DISTINCT if "
            f"it should, or WHERE {self.nullable[0]} IS NOT NULL if the exemption "
            f"is meant"
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


def _is_field(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "fields"
    )


def _declares_required(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg == "required":
            return _literal(keyword.value) is True
    return False


def collect(tree: ast.Module) -> list[ClassInfo]:
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and looks_like_model_class(node)):
            continue
        names: tuple[str, ...] = ()
        inherits: tuple[str, ...] = ()
        required: dict[str, bool] = {}
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
            elif isinstance(value, ast.Call):
                func = value.func
                attr = func.attr if isinstance(func, ast.Attribute) else None
                if attr in ("Constraint", "UniqueIndex") and value.args:
                    text = _literal(value.args[0])
                    if isinstance(text, str):
                        rules.append((key, text, stmt.lineno, attr == "UniqueIndex"))
                elif not key.startswith("_") and _is_field(value):
                    required[key] = _declares_required(value)

        model = names[0] if names else (inherits[0] if inherits else None)
        if not model:
            continue
        parents = tuple(p for p in inherits if p != model) if names else ()
        out.append(ClassInfo(model, parents, required, rules))
    return out


def resolve_required(infos: list[ClassInfo]) -> dict[str, dict[str, bool]]:
    """{model: {field: required}} folded over every declaration and _inherit.

    required wins over not-required wherever two declarations disagree: one
    ``required=True`` anywhere is what puts NOT NULL on the column.
    """
    own: dict[str, dict[str, bool]] = {}
    parents: dict[str, set[str]] = {}
    for info in infos:
        bucket = own.setdefault(info.model, {})
        for name, flag in info.required.items():
            bucket[name] = bucket.get(name, False) or flag
        parents.setdefault(info.model, set()).update(info.parents)

    resolved = {model: dict(fields_) for model, fields_ in own.items()}
    changed = True
    while changed:
        changed = False
        for model, fields_ in resolved.items():
            for parent in parents.get(model, ()):
                for name, flag in resolved.get(parent, {}).items():
                    merged = fields_.get(name, False) or flag
                    if name not in fields_ or fields_[name] != merged:
                        fields_[name] = merged
                        changed = True
    return resolved


def _column_list(text: str) -> str | None:
    """The text between the first balanced parentheses, or None."""
    start = text.find("(")
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    return None


def _split_top_level(raw: str) -> list[str]:
    parts, depth, current = [], 0, []
    for char in raw:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _columns(text: str) -> tuple[str, ...] | None:
    """The plain column names of this constraint, or None if it is not a plain
    column list.

    A functional index -- lower(name), COALESCE(warehouse_id, 0) -- is a
    different animal: COALESCE is how a key deliberately folds its NULLs, and
    judging the rest needs semantics this checker does not have. Those are left
    alone rather than guessed at.
    """
    raw = _column_list(text)
    if raw is None:
        return None
    tokens = _split_top_level(raw)
    columns = []
    for token in tokens:
        bare = token.strip().strip('"').strip("'")
        if not _BARE_COLUMN.fullmatch(bare):
            return None
        columns.append(bare)
    return tuple(columns)


def violations(units: list[tuple[str, list[ClassInfo]]]) -> Iterator[Violation]:
    required = resolve_required([info for _path, infos in units for info in infos])
    for path, infos in units:
        for info in infos:
            known = required.get(info.model, {})
            for attribute, text, lineno, is_index in info.rules:
                if not is_index and not _UNIQUE_COLUMNS.search(text):
                    continue
                if _NULLS_NOT_DISTINCT.search(text) or _PARTIAL.search(text):
                    continue
                columns = _columns(text)
                if columns is None or len(columns) < 2:
                    continue
                nullable = tuple(c for c in columns if known.get(c) is False)
                if nullable:
                    yield Violation(
                        path, lineno, info.model, attribute, columns, nullable
                    )
