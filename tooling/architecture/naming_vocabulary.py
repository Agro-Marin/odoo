"""Method-naming vocabulary gate: one verb per operation (§2.4).

``doc/coding_guidelines.rst`` §2.4 fixes one canonical verb per operation and
abolishes the synonyms that used to compete with it. This gate counts the
definitions still spelled the abolished way, so the backlog is a number the
shared ratchet can pin rather than a claim in a document.

Why a count and not a hard failure
----------------------------------
The tree opens with hundreds of these. A blocking gate would fail every build
on day one and be switched off within a week; the ratchet instead freezes the
number where it stands, fails on any increase, and makes each cleanup batch
lower the floor permanently. That is the same shape ``jsfunclen`` and
``jsserviceshape`` use::

    python tooling/architecture/naming_vocabulary.py --count \\
        | xargs python tooling/ratchet/ratchet.py naming --count

What it deliberately does NOT count
-----------------------------------
Three §2.4 rules are real but not mechanically decidable, and a ratchet number
nobody can lower by reading the rule is a number people learn to ignore:

* **The ``_get_``/``_prepare_`` split** (1,681 candidate definitions). §2.4's
  discriminator is *"does the return value feed create()/write()/Command"* —
  a question about the caller, not the name. Counting every payload-shaped
  ``get_*`` would pin ~1,681 of which an unknown fraction are correct as-is.
* **The EXEC verbs** (``_do_``, ``_run_``, ``_perform_``, ``_execute_``,
  ``_process_``, ``_handle_``). §2.4 ships this rule marked *provisional*; the
  replacement is "name the domain operation", which no script can generate.
* **``_set_`` vs ``_update_``.** Also *provisional* in §2.4, and a near-even
  368/357 split. The boundary moves; the baseline should not.

``_build_``/``_make_``/``_compose_``/``_construct_`` are counted **only** on
payload-shaped names (``_vals``, ``_values``, ``_data``, ``_dict``, ``_domain``,
``_context``, ``_defaults``, ``_list``, ``_args``, ``_params``). ``_build_url``
is not a payload builder and §2.4's Payload row does not reach it; scoping by
suffix keeps the count to cases the rule actually decides. The other abolished
verbs have no such ambiguity and are counted outright.

Scope is the odoo checkout — ``odoo/`` and ``addons/`` — matching the ruff
ratchet, which also measures this repo only. ``enterprise`` and ``agromarin``
are separate repositories and need their own baselines; ``--roots`` points the
same measurement at them.

Usage::

    python tooling/architecture/naming_vocabulary.py            # report
    python tooling/architecture/naming_vocabulary.py --count    # the number only
    python tooling/architecture/naming_vocabulary.py --json
    python tooling/architecture/naming_vocabulary.py --verb validate
    python tooling/architecture/naming_vocabulary.py --roots ../enterprise
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

# Located by marker, not by counting parents — see _repo_root.
ROOT = find_odoo_root(Path(__file__).resolve())
SCAN_ROOTS = ("odoo", "addons")

# Directories holding no model code, or code that is not ours to rename.
SKIP_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".mypy_cache", "static", "lib", "vendored"}
)

PAYLOAD_SUFFIXES = (
    "_vals",
    "_values",
    "_data",
    "_dict",
    "_domain",
    "_context",
    "_defaults",
    "_list",
    "_args",
    "_params",
)

# abolished verb -> (canonical replacement, only when payload-shaped)
ABOLISHED: dict[str, tuple[str, bool]] = {
    "build": ("_prepare_", True),
    "make": ("_prepare_", True),
    "compose": ("_prepare_", True),
    "construct": ("_prepare_", True),
    "fetch": ("_get_", False),
    "retrieve": ("_get_", False),
    "obtain": ("_get_", False),
    "lookup": ("_get_", False),
    "validate": ("_check_", False),
    "verify": ("_check_", False),
    "ensure": ("_check_", False),
    "control": ("_check_", False),
    "assign": ("_update_", False),
    "fill": ("_update_", False),
    "inject": ("_update_", False),
    "append": ("_add_", False),
    "delete": ("_remove_", False),
    "purge": ("_remove_", False),
}

# Verbs §2.4 reserves rather than abolishes, because each is a precise term of
# art borrowed from a layer below the ORM. Measuring them was tried and
# reverted: the first run flagged `_drop_table` / `_drop_column` (SQL DDL),
# `_insert_cache` / `insert_rows` (SQL DML), `push_protection` (a stack push)
# and `discard_field` (the `set.discard` contract, where discard-vs-remove is a
# real distinction, not a synonym). Renaming any of them to `_remove_*` /
# `_add_*` would destroy information rather than standardise it.
RESERVED = {
    "drop": "SQL DDL",
    "insert": "SQL DML",
    "push": "stack / queue",
    "discard": "set.discard — remove if present, never raise",
}


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    name: str
    verb: str
    canonical: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.name}  ->  {self.canonical}*"


def classify(name: str) -> tuple[str, str] | None:
    """Return ``(verb, canonical)`` if ``name`` opens with an abolished verb."""
    if name.startswith("__") and name.endswith("__"):
        return None
    stem = name.lstrip("_")
    verb, _, rest = stem.partition("_")
    if not rest:  # a bare verb ("create", "write") is an ORM hook, not a name we own
        return None
    entry = ABOLISHED.get(verb)
    if entry is None:
        return None
    canonical, payload_only = entry
    if payload_only and not name.endswith(PAYLOAD_SUFFIXES):
        return None
    return verb, canonical


MODEL_BASES = frozenset({"Model", "TransientModel", "AbstractModel", "BaseModel"})


def is_model_class(node: ast.ClassDef) -> bool:
    """Is this an Odoo model class?

    §2.4 governs *model* method naming. The framework packages below the ORM —
    ``odoo/db``, ``odoo/http``, ``odoo/tools``, ``odoo/orm`` internals — speak
    SQL and Python data-structure vocabulary legitimately, and holding them to a
    business-operation verb list produces exactly the false positives that
    teach people to ignore a gate.
    """
    for base in node.bases:
        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        if name in MODEL_BASES:
            return True
    # Inheritance-only extensions (`class SaleOrder(models.Model)` is the norm,
    # but `_inherit` alone appears in older files and in mixin re-openings).
    return any(
        isinstance(stmt, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id in ("_name", "_inherit")
            for t in stmt.targets
        )
        for stmt in node.body
    )


def _python_files(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            parts = set(path.parts)
            if parts & SKIP_DIRS:
                continue
            if "tests" in parts or path.name.startswith("test_"):
                continue
            found.append(path)
    return found


def _display(path: Path) -> Path:
    """Repo-relative where possible — ``--roots`` may point outside this checkout."""
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


def measure(roots: list[Path] | None = None) -> list[Violation]:
    """Every class-level method whose name opens with an abolished verb.

    Raises ``RuntimeError`` rather than returning an empty list when there is
    nothing to scan. An empty scan prints 0, and 0 against a ratchet floor of
    several hundred reads exactly like a tree that fixed them all — the failure
    mode this gate exists to prevent.
    """
    roots = roots or [ROOT / r for r in SCAN_ROOTS]
    files = _python_files(roots)
    if not files:
        raise RuntimeError(
            f"no Python files under {', '.join(str(r) for r in roots)} — "
            f"refusing to report a count from an empty scan"
        )

    out: list[Violation] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError, UnicodeDecodeError:
            continue  # not ours to parse; ruff owns syntax
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not is_model_class(node):
                continue
            for item in node.body:
                if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                hit = classify(item.name)
                if hit is None:
                    continue
                out.append(
                    Violation(
                        path=str(_display(path)),
                        line=item.lineno,
                        name=item.name,
                        verb=hit[0],
                        canonical=hit[1],
                    )
                )
    out.sort(key=lambda v: (v.path, v.line))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verb", help="restrict the report to one abolished verb")
    parser.add_argument(
        "--roots", nargs="+", help="scan these paths instead of odoo/ and addons/"
    )
    parser.add_argument(
        "--top", type=int, default=20, help="offenders to list (0 = all)"
    )
    args = parser.parse_args(argv)

    roots = [Path(r).resolve() for r in args.roots] if args.roots else None
    try:
        found = measure(roots)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.verb:
        found = [v for v in found if v.verb == args.verb]

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(v) for v in found], indent=2))
        return 0

    print("Method-naming vocabulary (§2.4 abolished verbs)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(f"  {item}")
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)

    by_verb = collections.Counter(v.verb for v in found)
    by_canon: collections.Counter[str] = collections.Counter()
    for v in found:
        by_canon[v.canonical] += 1
    print(f"\n{len(found)} definition(s) using an abolished verb\n")
    print("  by canonical target:")
    for canon, n in by_canon.most_common():
        verbs = sorted({v.verb for v in found if v.canonical == canon})
        print(f"    {canon + '*':<12}{n:>5}   from {', '.join(verbs)}")
    print("\n  by verb:")
    for verb, n in by_verb.most_common():
        print(f"    _{verb}_{'':<8}{n:>5}")

    print("\nRatchet this number:")
    print("  python tooling/architecture/naming_vocabulary.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py naming --count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
