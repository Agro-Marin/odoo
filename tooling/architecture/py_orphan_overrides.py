#!/usr/bin/env python3
"""A `super()` call in a model class reaches a method some other class defines.

`super()._x()` inside an Odoo model is only meaningful if `_x` exists somewhere
else in the model's MRO. When a method is renamed and one of its overrides is
not, the override keeps the old name -- so it still parses, still imports, still
registers on the model, and calls nothing. Python says nothing until the line
runs, and its `super()` then raises `AttributeError` naming a method that looks
present in the source.

WHY THIS IS NOT `py_unresolved_calls.py`. That gate asks whether a called name
is bound anywhere in the checkout, and for this shape the answer is yes: the
name IS defined -- by the very class whose `super()` cannot find a parent. So
the sibling gate resolves it and reports nothing. The two gates ask different
questions about the same call and neither subsumes the other.

WHAT THE FORK'S RENAMES ACTUALLY LEFT BEHIND, all found by this scan rather
than by reading, and all in one family of modules:

    _compute_price_unit_and_date_commitment_and_name  split into three computes
    _must_delete_date_planned                        -> _must_delete_date_commitment
    _get_product_purchase_description                -> _set_product_description
    _product_id_change                               replaced by computed fields

The first two changed behaviour silently -- a product grid stopped clearing an
expected-arrival date, an agreement's description stopped reaching its order
line. The third was dead *and* redundant, its body having moved into the core
module in the same refactor. The fourth was not latent at all: it raised on
every product-grid edit and had been failing a tour for as long as it existed.
One rename, four orphans, three modules, and no gate that could see any of it.

RESOLVED PER MODEL, BECAUSE "DEFINED ANYWHERE" HID TEN OF THEM. The first cut
of this gate counted a name as resolved if any class in the tree defined it.
The fork renamed `sale.order._prepare_invoice` to `_prepare_invoice_vals`, and ten
`sale.order` overrides of `_prepare_invoice` across the Italian, Brazilian,
Chilean, Ecuadorian, Indian and Taiwanese localisations, intrastat and Amazon's
Avatax bridge went on calling a parent that no longer exists -- and that first cut
reported none of them, because `purchase.order` defines a `_prepare_invoice` of its
own. A method on an unrelated model is not a parent. So a `super()._x()` in a class
of model M resolves only against: the other classes that extend M, every model M
reaches through `_inherit` transitively, and the methods `BaseModel` is composed
of -- including every class that extends the model named `base`, which the
registry grafts onto every model there is. And an override is never a parent:
a definition that calls `super()` on its own name implements nothing, so ten
overrides of one vanished method cannot vouch for each other, and the ten
`_prepare_invoice` orphans stay findings even though each one sees nine more.

TWO QUESTIONS, EITHER ONE A FINDING. A name no other class anywhere in the
scanned roots defines has no parent in any MRO this tree can build, whatever the
model's ancestry looks like; that half needs no model graph and cannot invent a
finding. The other half is the per-model resolution above, and it is judged only
where the whole ancestry is visible. An abstract mixin is resolved against what it
is mixed INTO as well as what it inherits: `mixin.hr.leave.approval` calls
`super().message_subscribe()`, and the parent is `mail.thread`, which the mixin
never names but every model combining the two does.

STILL CONSERVATIVE, IN THE SAME ONE DIRECTION. What the registry knows and this
scan does not is load ORDER: an implementation in another extension of the same
model counts as a parent here even where the module graph would load it after the
override that needs it. And the per-model half does not judge a model whose
ancestry leaves the scanned roots -- an `_inherit` naming a model no scanned class
declares -- nor a class with a Python base this tree does not define, rather than
judging either against half its MRO. Both can hide a genuine orphan; neither can
invent one. The count is a floor on the problem, and a finding here is a finding.

ONLY MODEL CLASSES ARE SCANNED. A class whose bases this scan cannot see is not
a question it can answer: subclasses of `xmlrpc.client.Marshaller`,
`email.policy.EmailPolicy`, an OFX parser and a Bluetooth driver all call
`super()` on methods their library bases define and this tree does not.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sources
from _repo_root import find_odoo_root

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ast_cache

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_orphan_overrides")

SCOPES = (ROOT / "odoo", ROOT / "addons")

MODEL_BASES = frozenset({"Model", "AbstractModel", "TransientModel", "BaseModel"})


@dataclass(frozen=True)
class OrphanOverride:
    file: str
    line: int
    cls: str
    name: str
    source: str

    def __str__(self) -> str:
        return f"  {self.file}:{self.line}  {self.cls}.{self.name}\n      {self.source}"


@dataclass(frozen=True)
class _Class:
    path: Path
    name: str
    bases: tuple[str, ...]
    defs: frozenset[str]
    model: str | None
    parents: tuple[str, ...]
    overrides: frozenset[str]
    calls: tuple[tuple[int, str], ...]


def _base_names(node: ast.ClassDef) -> tuple[str, ...]:
    return tuple(
        base.attr
        if isinstance(base, ast.Attribute)
        else base.id
        if isinstance(base, ast.Name)
        else ""
        for base in node.bases
    )


def _strings(value: ast.expr) -> list[str]:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return [value.value]
    if isinstance(value, (ast.List, ast.Tuple)):
        return [
            elt.value
            for elt in value.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        ]
    return []


def _model_identity(node: ast.ClassDef) -> tuple[str | None, tuple[str, ...]]:
    name: str | None = None
    inherit: list[str] = []
    for stmt in node.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            target, value = stmt.target, stmt.value
        else:
            continue
        if not isinstance(target, ast.Name):
            continue
        if target.id == "_name":
            name = next(iter(_strings(value)), None)
        elif target.id == "_inherit":
            inherit = _strings(value)
    model = name or next(iter(inherit), None)
    return model, tuple(parent for parent in inherit if parent != model)


def _super_calls(cls: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(cls)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Call)
        and isinstance(node.func.value.func, ast.Name)
        and node.func.value.func.id == "super"
    ]


def iter_source_files(scopes: tuple[Path, ...] = SCOPES) -> list[Path]:
    return sorted(
        p
        for scope in scopes
        for p in scope.rglob("*.py")
        if "__pycache__" not in p.parts
    )


class _Index:
    def __init__(self, classes: list[_Class]) -> None:
        self.by_python_name: defaultdict[str, list[_Class]] = defaultdict(list)
        self.by_model: defaultdict[str, list[_Class]] = defaultdict(list)
        self.definers: defaultdict[str, list[_Class]] = defaultdict(list)
        for cls in classes:
            self.by_python_name[cls.name].append(cls)
            if cls.model:
                self.by_model[cls.model].append(cls)
            for name in cls.defs:
                self.definers[name].append(cls)
        self.universe = self._lineage_defs(MODEL_BASES)[0].union(
            *(cls.defs for cls in self.by_model.get("base", ()))
        )
        self.opaque = {
            cls.model
            for cls in classes
            if cls.model and not self._lineage_defs(self._extra_bases(cls))[1]
        }
        self._ancestry: dict[str, tuple[frozenset[str], bool]] = {}
        self._downstream: defaultdict[str, set[str]] | None = None

    @staticmethod
    def _extra_bases(entry: _Class) -> list[str]:
        return [base for base in entry.bases if base and base not in MODEL_BASES]

    def _lineage_defs(self, names) -> tuple[frozenset[str], bool]:
        defs: set[str] = set()
        known = True
        seen: set[str] = set()
        queue = list(names)
        while queue:
            name = queue.pop()
            if name in seen or name == "object":
                continue
            seen.add(name)
            found = self.by_python_name.get(name)
            if not found:
                known = known and name in MODEL_BASES
                continue
            for cls in found:
                defs |= cls.defs
                queue.extend(cls.bases)
        return frozenset(defs), known

    def ancestry(self, model: str) -> tuple[frozenset[str], bool]:
        if model not in self._ancestry:
            seen: set[str] = set()
            known = True
            queue = [p for cls in self.by_model[model] for p in cls.parents]
            while queue:
                parent = queue.pop()
                if parent in seen or parent == model:
                    continue
                seen.add(parent)
                classes = self.by_model.get(parent)
                if not classes:
                    known = False
                    continue
                queue.extend(p for cls in classes for p in cls.parents)
            self._ancestry[model] = (frozenset(seen), known)
        return self._ancestry[model]

    def downstream(self, model: str) -> set[str]:
        if self._downstream is None:
            self._downstream = defaultdict(set)
            for inheritor in list(self.by_model):
                for ancestor in self.ancestry(inheritor)[0]:
                    self._downstream[ancestor].add(inheritor)
        return self._downstream[model]

    def _implementers(self, name: str, caller: _Class) -> set[str]:
        return {
            cls.model
            for cls in self.definers.get(name, ())
            if cls is not caller and cls.model and name not in cls.overrides
        }

    def resolves(self, cls: _Class, name: str) -> bool:
        if name in self.universe:
            return True
        extra, extra_known = self._lineage_defs(self._extra_bases(cls))
        if name in extra or not extra_known:
            return True
        if not any(other is not cls for other in self.definers.get(name, ())):
            return cls.model in self.opaque
        implementers = self._implementers(name, cls)
        if cls.model in implementers:
            return True
        ancestors, known = self.ancestry(cls.model)
        if ancestors & implementers or not known:
            return True
        for inheritor in self.downstream(cls.model):
            if inheritor in implementers:
                return True
            branch, branch_known = self.ancestry(inheritor)
            if not branch_known or (branch - ancestors - {cls.model}) & implementers:
                return True
        return False


def measure(
    scopes: tuple[Path, ...] = SCOPES,
    report_scopes: tuple[Path, ...] | None = None,
) -> list[OrphanOverride]:
    files = iter_source_files(scopes)
    if not files:
        raise RuntimeError(
            f"no Python sources under {', '.join(str(s) for s in scopes)} -- the "
            f"scan found nothing, which is not the same as finding nothing wrong"
        )

    classes: list[_Class] = []
    for path in files:
        tree = _ast_cache.parse_source(path.read_text(encoding="utf-8"), path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = _base_names(node)
            is_model = any(base in MODEL_BASES for base in bases)
            model, parents = _model_identity(node) if is_model else (None, ())
            methods = [
                stmt
                for stmt in node.body
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            classes.append(
                _Class(
                    path,
                    node.name,
                    bases,
                    frozenset(stmt.name for stmt in methods),
                    model if is_model else None,
                    parents,
                    frozenset(
                        stmt.name
                        for stmt in methods
                        if any(
                            call.func.attr == stmt.name for call in _super_calls(stmt)
                        )
                    ),
                    tuple((call.lineno, call.func.attr) for call in _super_calls(node))
                    if is_model
                    else (),
                )
            )

    index = _Index(classes)

    def reported(path: Path) -> bool:
        return report_scopes is None or any(
            path.is_relative_to(scope) for scope in report_scopes
        )

    lines_by_path: dict[Path, list[str]] = {}
    found = []
    for cls in classes:
        if not cls.model or not cls.calls or not reported(cls.path):
            continue
        for lineno, name in cls.calls:
            if index.resolves(cls, name):
                continue
            if cls.path not in lines_by_path:
                lines_by_path[cls.path] = cls.path.read_text(
                    encoding="utf-8"
                ).splitlines()
            found.append(
                OrphanOverride(
                    _sources.display(cls.path, ROOT),
                    lineno,
                    cls.name,
                    name,
                    lines_by_path[cls.path][lineno - 1].strip(),
                )
            )
    found.sort(key=lambda o: (o.name, o.file, o.line))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=30, help="0 for all")
    parser.add_argument(
        "--also-define",
        nargs="+",
        metavar="PATH",
        help="read these paths for definitions but never report their call "
        "sites. A sibling repository measured without the repositories it "
        "depends on reports a count inflated by that blindness; this "
        "reproduces the true reading locally. It is NOT what the floor "
        "measures -- the bare invocation is.",
    )
    parser.add_argument(
        "--roots",
        nargs="+",
        help="report overrides from these paths instead of odoo/ and addons/; "
        "the definitions of odoo/ and addons/ still count as supplying a "
        "parent, so a sibling repository is measured against the framework it "
        "runs on",
    )
    args = parser.parse_args(argv)

    def resolved(paths: list[str], flag: str) -> tuple[Path, ...]:
        out = []
        for raw in paths:
            path = Path(raw).resolve()
            if not path.is_dir():
                msg = f"{flag} {raw}: not a directory (resolved to {path})"
                raise RuntimeError(msg)
            if not any(p for p in path.rglob("*.py") if "__pycache__" not in p.parts):
                msg = f"{flag} {raw}: no Python sources under {path}"
                raise RuntimeError(msg)
            out.append(path)
        return tuple(out)

    report_scopes = None
    scopes = SCOPES
    try:
        if args.roots:
            report_scopes = resolved(args.roots, "--roots")
            scopes = SCOPES + report_scopes
        if args.also_define:
            scopes += resolved(args.also_define, "--also-define")
            if report_scopes is None:
                report_scopes = SCOPES
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        found = measure(scopes, report_scopes)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(o) for o in found], indent=2))
        return 0

    print("super() calls in model classes whose method no other class defines")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for orphan in shown:
        print(orphan)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more")
    print("-" * 72)
    print()
    names = {o.name for o in found}
    print(f"{len(found)} override(s) over {len(names)} name(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
