import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from ._checker_unlink import looks_like_model_class

_UNIQUE_COLUMNS = re.compile(
    r"unique\s*(?:nulls\s+not\s+distinct\s*)?\(([^)]*)\)", re.IGNORECASE
)
_INDEX_COLUMNS = re.compile(r"^\s*\(([^)]*)\)")
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*", re.IGNORECASE)


@dataclass
class ClassInfo:
    model: str
    parents: tuple[str, ...] = ()
    translated: set[str] = field(default_factory=set)
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
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and looks_like_model_class(node)):
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
    own: dict[str, set[str]] = {}
    parents: dict[str, set[str]] = {}
    for info in infos:
        own.setdefault(info.model, set()).update(info.translated)
        parents.setdefault(info.model, set()).update(info.parents)

    # A recursive walk that caches a model's result as soon as its *immediate*
    # parents are not on the active call stack isn't enough: in a cycle of
    # length >= 3, the middle node finishes and gets cached before the cycle
    # closes, with an incomplete field set that's never corrected. A
    # fixed-point closure sidesteps the problem instead of chasing it: start
    # every model at its own fields and keep merging each parent's current
    # fields in until nothing changes. A real cycle (illegal for a real Odoo
    # `_inherit` graph, but possible in this checker's own input) converges
    # every member to the same union rather than caching a stale fragment.
    resolved: dict[str, set[str]] = {
        model: set(fields_) for model, fields_ in own.items()
    }
    changed = True
    while changed:
        changed = False
        for model, fields_ in resolved.items():
            for parent in parents.get(model, ()):
                parent_fields = resolved.get(parent)
                if parent_fields and not parent_fields <= fields_:
                    fields_ |= parent_fields
                    changed = True
    return resolved


def _columns(text: str, is_index: bool) -> tuple[str, ...]:
    match = (_INDEX_COLUMNS if is_index else _UNIQUE_COLUMNS).search(text)
    if not match:
        return ()
    return tuple(
        token.strip().strip('"').strip("'") for token in match.group(1).split(",")
    )


def violations(units: list[tuple[str, list[ClassInfo]]]) -> Iterator[Violation]:
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
                    columns = tuple(
                        token
                        for column in columns
                        for token in _IDENTIFIER.findall(column)
                    )
                hit = tuple(c for c in columns if c.lower() in lowered)
                if hit:
                    yield Violation(path, lineno, info.model, attribute, hit)
