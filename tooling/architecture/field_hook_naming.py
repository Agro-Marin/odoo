"""Field hooks are named after the field they serve.

``doc/coding_guidelines.rst`` §2.4 fixes the prefix for a compute, search,
inverse, default or domain method. It does not say what follows the prefix, and the
answer is not free: the field declaration already names the method, so the two
strings sit inches apart and can disagree. When they do, a reader looking for
what writes ``reconciled`` has nothing to grep for.

Two shapes are reported, and the second is the reason this gate exists:

* a hook serving ONE field whose name is not ``_<attr>_<field>``;
* a hook serving SEVERAL fields but named after exactly one of them, which
  promises a single field and quietly writes the rest.

Both are decidable from the declaration alone -- the field name and the method
name are in the same call -- which is what makes them countable at all. The
count is global rather than per-file on purpose: whether ``_compute_amounts``
may keep its name depends on how many fields point at it, and no single file
knows that.
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _ast_cache
import naming_vocabulary as nv
from _repo_root import find_odoo_root

ADR = "0049"

ROOT = find_odoo_root(Path(__file__).resolve())

#: The field attributes that name a method. ``related`` is absent on purpose:
#: it names a field path, not a hook.
ATTRS = ("compute", "search", "inverse", "default", "domain")

#: ADR-0054: a free-standing domain builder leads with the verb and puts its
#: object next -- ``_get_domain_<what>``, or ``get_domain_<what>`` public. A bare
#: ``_get_domain`` qualifies: there is nothing left to qualify. This supersedes
#: ADR-0050's suffix, which asked the same family to sort the other way round
#: from every other head noun §2.4 governs.
_HEAD_FIRST_DOMAIN = re.compile(r"_?get_domain(_[a-z0-9_]+)?$")

#: ``default=`` and ``domain=`` accept any callable and may point at a shared
#: helper, so both take the dedication test below. The other three name a hook
#: by construction.
_CALLABLE_ATTRS = ("default", "domain")

#: ``default=SOME_CONSTANT`` references a value, not a hook, so the rule has
#: nothing to say about it.
_CONSTANT = re.compile(r"^[A-Z0-9_]+$")


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    attr: str
    method: str
    field: str
    kind: str  # "misnamed" | "misleading" | "unmarked"

    def __str__(self) -> str:
        if self.kind == "unmarked":
            return (
                f"{self.path}:{self.line}  {self.method}  returns a domain and "
                f"does not say so first -- name it _get_domain_<what>"
            )
        if self.kind == "misleading":
            return (
                f"{self.path}:{self.line}  {self.method}  serves several fields "
                f"but is named for {self.field} alone"
            )
        return f"{self.path}:{self.line}  {self.method}  ->  _{self.attr}_{self.field}"


def _hook_name(attr: str, value: ast.expr) -> str | None:
    """The method ``value`` names, or None when it names no method.

    ``compute``/``search``/``inverse`` take a string. ``default`` takes a
    callable: a bare reference, or a lambda whose entire body is one
    argument-less call on ``self``. A lambda doing any work of its own -- even
    one line of it -- *is* the hook, and the method it calls is a helper it
    reached for. Judging that helper against the field would demand a name for
    a job it does not have: ``lambda self: self._selection_duration()[0][0]``
    would rename a Selection provider ``_default_duration``.
    """
    if attr not in _CALLABLE_ATTRS:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        return None
    if attr == "domain" and isinstance(value, ast.Constant):
        # a domain given as a string expression or a literal names no method
        return None
    if isinstance(value, ast.Lambda):
        # Only a lambda that forwards to a method ON SELF names a hook.
        # ``lambda self: ",".join(...)`` or ``lambda self: self.env[m].get_x()``
        # compute the default inline; there is no hook name to check, and
        # reading one out of them reports ``join`` as a field's default method.
        body = value.body
        if (
            isinstance(body, ast.Call)
            and isinstance(body.func, ast.Attribute)
            and isinstance(body.func.value, ast.Name)
            and body.func.value.id == "self"
            and not body.args
            and not body.keywords
        ):
            return body.func.attr
        return None
    if isinstance(value, ast.Attribute):
        # ``default=fields.Datetime.now`` names a framework helper, not a method
        # on this model; there is nothing here for a naming rule to reach.
        root = value.value
        while isinstance(root, ast.Attribute):
            root = root.value
        if isinstance(root, ast.Name) and root.id == "fields":
            return None
        return None if _CONSTANT.match(value.attr) else value.attr
    if isinstance(value, ast.Name):
        return None if _CONSTANT.match(value.id) else value.id
    return None


#: The comparison operators a domain leaf may carry.
_OPERATORS = frozenset(
    {
        "=",
        "!=",
        ">",
        ">=",
        "<",
        "<=",
        "=?",
        "like",
        "not like",
        "ilike",
        "not ilike",
        "=like",
        "=ilike",
        "in",
        "not in",
        "child_of",
        "parent_of",
        "any",
        "not any",
    }
)


def _returns_domain(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when every ``return`` in ``node`` yields a domain literal.

    A domain leaf is a 3-tuple of (field, operator, value). Both halves of that
    test are load-bearing: an x2many ``Command`` -- ``(6, 0, ids)`` -- has the
    same shape with an integer first, and a plain mapping table such as
    ``utm.mixin.tracking_fields`` has three strings and no operator.
    """
    returns = [
        r.value
        for r in ast.walk(node)
        if isinstance(r, ast.Return) and r.value is not None
    ]
    if not returns:
        return False

    def is_domain(value: ast.expr) -> bool:
        if isinstance(value, ast.List | ast.Tuple):
            return not value.elts or any(
                isinstance(element, ast.Tuple)
                and len(element.elts) == 3
                and isinstance(element.elts[0], ast.Constant)
                and isinstance(element.elts[0].value, str)
                and isinstance(element.elts[1], ast.Constant)
                and element.elts[1].value in _OPERATORS
                for element in value.elts
            )
        return (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "Domain"
        )

    return all(is_domain(value) for value in returns) and any(
        isinstance(value, ast.List | ast.Tuple) and value.elts for value in returns
    )


def _model_of(node: ast.ClassDef) -> str | None:
    """The model a class declares, from ``_name`` or the first ``_inherit``."""
    inherited = None
    for stmt in node.body:
        if not isinstance(stmt, ast.Assign) or not isinstance(
            stmt.targets[0], ast.Name
        ):
            continue
        target = stmt.targets[0].id
        if target not in ("_name", "_inherit"):
            continue
        value = stmt.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            if target == "_name":
                return value.value
            inherited = inherited or value.value
        elif isinstance(value, ast.List | ast.Tuple) and value.elts:
            first = value.elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                if target == "_name":
                    return first.value
                inherited = inherited or first.value
    return inherited


def _field_hooks(tree: ast.Module) -> list[tuple[str, str, str, str, int]]:
    """Every (model, attr, method, field, line) a model class in ``tree`` declares.

    Keyed by model, not by method name alone: two models may legitimately give
    the same hook the same name -- three carry ``_default_employee_id`` -- and
    merging their field sets invents multi-field hooks that do not exist.
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not nv.is_model_class(node):
            continue
        model = _model_of(node)
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                continue
            target = stmt.targets[0]
            call = stmt.value
            if not isinstance(target, ast.Name) or not isinstance(call, ast.Call):
                continue
            func = call.func
            if not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "fields"
            ):
                continue
            for keyword in call.keywords:
                if keyword.arg not in ATTRS:
                    continue
                method = _hook_name(keyword.arg, keyword.value)
                if method:
                    out.append(
                        (model or "?", keyword.arg, method, target.id, stmt.lineno)
                    )
    return out


#: A ``default=`` may point at any callable, including a shared utility the
#: field merely happens to use. ``get_base_url`` has 243 callers and is the
#: default of one URL field; demanding it be renamed ``_default_adyen_event_url``
#: would be absurd. So the rule reaches a default only when the method exists
#: FOR that field -- its name appears about as often as a definition plus the
#: declaration that points at it. ``compute``/``search``/``inverse`` need no such
#: test: those attributes name a hook by construction.
#:
#: PER DEFINITION, NOT PER NAME. This budget was once compared against the raw
#: occurrence count, which asks "how often is this name written" where it means
#: "how many callers does this method have". The two agree only while the name
#: has one definition. Eighteen classes that each declare their own dedicated
#: ``_get_default_color`` and each point one field at it spend the budget between
#: them and were exempted together -- so a misnamed hook grew harder to see the
#: more often it had been copy-pasted, and 25 hooks were hidden of which 15 were
#: that one name. Dividing by the number of definitions separates the two shapes:
#: a utility is one definition with many callers, a replicated hook is many
#: definitions with two uses each. A name defined once scores exactly as it did.
_DEDICATED_USES = 4


def _is_dedicated(
    method: str,
    uses: collections.Counter[str],
    definitions: collections.Counter[str],
) -> bool:
    return uses[method] <= _DEDICATED_USES * max(1, definitions[method])


def measure(roots: list[Path] | None = None) -> list[Violation]:
    roots = roots or [ROOT / r for r in nv.SCAN_ROOTS]
    files = nv._python_files(roots)
    if not files:
        raise RuntimeError(
            f"no Python files under {', '.join(str(r) for r in roots)} — "
            f"refusing to report a count from an empty scan"
        )

    # (model, attr, method) -> {field: (path, line)}
    seen: dict[tuple[str, str, str], dict[str, tuple[str, int]]] = (
        collections.defaultdict(dict)
    )
    uses: collections.Counter[str] = collections.Counter()
    definitions: collections.Counter[str] = collections.Counter()
    domain_methods: dict[str, tuple[str, int]] = {}
    for path in files:
        try:
            tree = _ast_cache.parse_file(path)
        except SyntaxError, UnicodeDecodeError:
            continue
        display = str(nv._display(path))
        for model, attr, method, field, line in _field_hooks(tree):
            seen[model, attr, method].setdefault(field, (display, line))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not nv.is_model_class(node):
                continue
            for item in node.body:
                if isinstance(
                    item, ast.FunctionDef | ast.AsyncFunctionDef
                ) and _returns_domain(item):
                    domain_methods.setdefault(item.name, (display, item.lineno))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                uses[node.attr] += 1
            elif isinstance(node, ast.Name):
                uses[node.id] += 1
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                uses[node.name] += 1
                definitions[node.name] += 1

    out: list[Violation] = []
    for (_model, attr, method), fields in seen.items():
        if attr in _CALLABLE_ATTRS and not _is_dedicated(method, uses, definitions):
            continue
        if len(fields) == 1:
            field, (path, line) = next(iter(fields.items()))
            if method != f"_{attr}_{field}":
                out.append(Violation(path, line, attr, method, field, "misnamed"))
            continue
        stem = method[len(attr) + 2 :] if method.startswith(f"_{attr}_") else None
        if stem in fields:
            path, line = fields[stem]
            out.append(Violation(path, line, attr, method, stem, "misleading"))
    # A method whose every return is a domain says so in its name, and says it
    # in front: ADR-0054 makes the free-standing builder ``_get_domain_<what>``,
    # superseding ADR-0050's suffix so that this family sorts the way every
    # other head noun does. The hooks a search= or domain= attribute names are
    # exempt: a domain is their contract, and ADR-0049 already fixes what they
    # are called -- the hook keeps ``_domain_<field>``, which is a prefix and
    # not a qualifier, and 0054 leaves it alone.
    hooked = {m for (_model, attr, m) in seen if attr in ("search", "domain")}
    for method, (path, line) in domain_methods.items():
        # ``_search_*`` is exempt by convention as well as by binding: it is the
        # shape ADR-0049 fixes for a search hook, and a hook whose field lives in
        # another module is not visible as a ``search=`` here.
        if (
            method in hooked
            or _HEAD_FIRST_DOMAIN.fullmatch(method)
            or method.startswith("_search_")
        ):
            continue
        out.append(Violation(path, line, "domain", method, "", "unmarked"))
    out.sort(key=lambda v: (v.path, v.line, v.method))
    return out


def inverse_spellings(roots: list[Path] | None = None) -> tuple[int, int]:
    """How many ``inverse=`` targets are spelled ``_inverse_`` and how many ``_set_``.

    ADR-0049 withdraws §2.4's ``_set_`` carve-out on this evidence, and §2.4
    states both numbers, so they are measured rather than typed.
    """
    roots = roots or [ROOT / r for r in nv.SCAN_ROOTS]
    inverse = setter = 0
    seen: set[tuple[str, str]] = set()
    for path in nv._python_files(roots):
        try:
            tree = _ast_cache.parse_file(path)
        except SyntaxError, UnicodeDecodeError:
            continue
        for _model, attr, method, field, _line in _field_hooks(tree):
            if attr != "inverse" or (method, field) in seen:
                continue
            seen.add((method, field))
            if method.startswith("_inverse_"):
                inverse += 1
            elif method.startswith("_set_"):
                setter += 1
    return inverse, setter


#: The seven prefixes §2.4 reserves for methods a field declaration points at.
#: ``selection`` and ``onchange`` are here and absent from ``ATTRS`` above: the
#: gate cannot ratchet them (a selection hook is not named for its field, and an
#: onchange binds through a decorator), but both prefixes are still reserved, so
#: both belong in the population this measurement sizes.
HOOK_PREFIXES = (
    "_compute_",
    "_search_",
    "_inverse_",
    "_default_",
    "_domain_",
    "_selection_",
    "_onchange_",
)

#: Bindings that are not a field declaration but still name the method.
_BINDING_DECORATORS = ("onchange", "depends", "constrains", "ondelete")

#: The ORM resolves these three by name whatever the declaration says.
_BOUND_BY_CONVENTION = frozenset(
    {"_compute_display_name", "_search_display_name", "_inverse_display_name"}
)

_IDENTIFIER = re.compile(r"_[A-Za-z0-9_]+")


def unbound_prefixes(roots: list[Path] | None = None) -> tuple[int, int]:
    """Hook-prefixed methods no field declaration names: (names, definitions).

    ``measure`` above reads the declaration and asks whether the method it names
    is spelled for the field. This asks the mirror question -- which methods wear
    a hook's prefix while NO declaration names them -- and it is the shape §2.4's
    *a hook's prefix is reserved for hooks* forbids, which neither field-hook
    gate can reach: this one builds its population FROM declarations, so a method
    no declaration names is not in it at all, and ``field_hook_purity`` counts
    hooks production code also calls, which is this shape inverted.

    The reading is deliberately generous to the tree, so the number is a floor.
    Every identifier inside a hook attribute counts as a binding -- a bare string,
    ``self._foo``, a lambda body -- because the point is to find prefixes nothing
    could plausibly have bound, not to audit how a binding is spelled. Names
    counted, not definitions, decide membership: one declaration anywhere in the
    tree clears the name everywhere, since an override in another addon is bound
    by its parent's declaration.
    """
    roots = roots or [ROOT / r for r in nv.SCAN_ROOTS]
    files = nv._python_files(roots)
    if not files:
        raise RuntimeError(
            f"no Python files under {', '.join(str(r) for r in roots)} — "
            f"refusing to report a count from an empty scan"
        )

    definitions: collections.Counter[str] = collections.Counter()
    bound: set[str] = set(_BOUND_BY_CONVENTION)
    for path in files:
        try:
            tree = _ast_cache.parse_file(path)
        except SyntaxError, UnicodeDecodeError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and nv.is_model_class(node):
                for stmt in node.body:
                    if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                        if stmt.name.startswith(HOOK_PREFIXES):
                            definitions[stmt.name] += 1
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                decorators = " ".join(ast.unparse(d) for d in node.decorator_list)
                if any(name in decorators for name in _BINDING_DECORATORS):
                    bound.add(node.name)
                continue
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "fields"
            ):
                continue
            for keyword in node.keywords:
                if keyword.arg in ATTRS or keyword.arg == "selection":
                    bound.update(_IDENTIFIER.findall(ast.unparse(keyword.value)))

    unbound = [name for name in definitions if name not in bound]
    return len(unbound), sum(definitions[name] for name in unbound)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--attr", choices=ATTRS, help="restrict to one attribute")
    parser.add_argument("--kind", choices=("misnamed", "misleading", "unmarked"))
    parser.add_argument("--roots", nargs="+", help="scan these paths instead")
    parser.add_argument(
        "--unbound",
        action="store_true",
        help="count hook-prefixed methods no field declaration names (§2.4)",
    )
    parser.add_argument("--top", type=int, default=20, help="offenders to list")
    args = parser.parse_args(argv)

    roots = [Path(r).resolve() for r in args.roots] if args.roots else None
    if args.unbound:
        try:
            names, defs = unbound_prefixes(roots)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"{names} name(s), {defs} definition(s)" if not args.count else names)
        return 0
    try:
        found = measure(roots)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.attr:
        found = [v for v in found if v.attr == args.attr]
    if args.kind:
        found = [v for v in found if v.kind == args.kind]

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(v) for v in found], indent=2))
        return 0

    print("Field-hook naming (§2.4: a hook is named for the field it serves)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(f"  {item}")
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)

    by_attr = collections.Counter(v.attr for v in found)
    by_kind = collections.Counter(v.kind for v in found)
    print(f"\n{len(found)} hook(s) not named for their field\n")
    print("  by attribute:")
    for attr, n in by_attr.most_common():
        print(f"    {attr + '=':<12}{n:>5}")
    print("\n  by kind:")
    for kind, n in by_kind.most_common():
        print(f"    {kind:<12}{n:>5}")

    print("\nRatchet this number:")
    print("  python tooling/architecture/field_hook_naming.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py fieldhooks --count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
