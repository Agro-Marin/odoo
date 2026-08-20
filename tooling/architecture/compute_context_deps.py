#!/usr/bin/env python3
"""Computes that read the acting user must say so — `@api.depends_context`.

A non-stored compute's cache is keyed by the context values its field declares
in ``depends_context``. Declare none and there is exactly **one** cache entry for
the whole transaction, so a compute that resolves ``self.env.user`` hands the
first reader's answer to every user after it. Nothing catches that: the ORM has
no way to know the method looked at ``env``, and a test transaction has one uid,
so a single-user test passes either way.

It is not a hypothetical. Six fields shipped it in `mail` and `sms`
simultaneously — ``message_is_follower``, ``message_needaction`` and its counter,
``message_has_error`` and its counter, ``message_has_sms_error`` — three of them
resolving ``self.env.user.partner_id.id`` straight into the WHERE clause of a
hand-written query. `discuss.channel._broadcast()` loops the partners it
broadcasts to, switching user each iteration, and the channel's store defaults
include ``message_needaction_counter``: creating a group chat therefore sent
every member but one the *first* member's unread badge count. Measured, with A
holding one unread message and B none::

    _broadcast(A then B) -> counters on the bus: [1, 1]
    _broadcast(B then A) -> counters on the bus: [0, 0]

Declaring the key fixed it and cost nothing — 0 query delta across 68 pinned
assertions — because a test transaction has one uid, which is the same reason no
test could have caught it.

**Syntactic, on purpose.** The accurate check needs the registry: whether the
method is a compute at all, and whether its field is stored. But `test_lint.yml`
installs only `test_lint` and its dependencies, so `mail` is not in that
registry, and the one place this bug class has actually shipped would be
invisible to a registry-based gate. Matching on ``_compute_*`` methods over the
source tree sees every addon whether it is installed or not, at the cost of
false positives — which is what a ratchet is for.

Two keys, both with a demonstrated failure behind them:

===============================  ===============
read in the body                 key it needs
===============================  ===============
``env.user`` / ``env.uid``       ``uid``
``_get_guest_from_context``      ``guest``
===============================  ===============

``env.company`` is deliberately **not** measured. It reads the same way
syntactically and does not mean the same thing: a compute resolving
``env.company`` is usually picking a default that is then stored, where the
per-user cache key is not the question. Measured at 96 findings against 94 for
``uid``, it would have doubled the floor with a signal of a different kind. A
`company` gate is a separate move on a separate baseline.

Precision on ``uid`` is high -- a sample of the findings holds
``_compute_move_ids`` branching on ``env.user.has_group``,
``_compute_order_count`` returning 0 "for users outside group", and
``_compute_invoice_default_user`` falling back on the current user. Each is the
same defect as the six mail fields, just not yet caught leaking.

A stored compute reading the acting user is a *worse* bug than an undeclared
context key — the answer is persisted for whoever wrote last — so it is reported
here too rather than excused; syntax cannot tell the two apart anyway.

Tests are out of scope: a fixture reading ``env.user`` inside a helper it happens
to have named ``_compute_x`` is not the failure this is about.

Usage::

  python tooling/architecture/compute_context_deps.py            # report
  python tooling/architecture/compute_context_deps.py --count    # for the ratchet
  python tooling/architecture/compute_context_deps.py --json
  python tooling/architecture/compute_context_deps.py --key uid  # one key only
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

ADR = "unrecorded"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="compute_context_deps")
SCAN_ROOTS = ("odoo", "addons")

#: context key -> the attribute reads that require it.
ENV_READS = {
    "uid": ("user", "uid"),
}
#: context key -> the call names that require it.
CALL_READS = {
    "guest": ("_get_guest_from_context",),
}


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    method: str
    key: str

    def __str__(self) -> str:
        return f"{self.key:<8} {self.file}:{self.line}  {self.method}"


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _is_test_path(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def _python_files(roots: list[Path]) -> list[Path]:
    return sorted(
        p
        for root in roots
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and not _is_test_path(p)
    )


def declared_keys(node: ast.FunctionDef) -> set[str]:
    """Context keys the method's own ``@api.depends_context`` decorators name."""
    keys: set[str] = set()
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "depends_context":
            continue
        for arg in decorator.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                keys.add(arg.value)
    return keys


def read_keys(node: ast.FunctionDef) -> set[str]:
    """Context keys the method's body implies it depends on."""
    keys: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute):
            # `<anything>.env.<attr>`: the receiver is `self` in a compute, but
            # matching on `.env.` rather than on `self` also catches the
            # `record.env.user` spelling a per-record loop tends to use.
            value = sub.value
            reads_env = (isinstance(value, ast.Attribute) and value.attr == "env") or (
                isinstance(value, ast.Name) and value.id == "env"
            )
            if reads_env:
                for key, attrs in ENV_READS.items():
                    if sub.attr in attrs:
                        keys.add(key)
        elif isinstance(sub, ast.Call):
            func = sub.func
            called = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", "")
            )
            for key, names in CALL_READS.items():
                if called in names:
                    keys.add(key)
    return keys


def measure(roots: list[Path] | None = None) -> list[Violation]:
    """Every ``_compute_*`` method reading context it does not declare.

    Raises ``RuntimeError`` rather than returning an empty list when there is
    nothing to scan: the count feeds an exact ratchet, so 0 from an empty scan
    reads exactly like a tree that declared every key.
    """
    roots = roots or [ROOT / r for r in SCAN_ROOTS]
    files = _python_files(roots)
    if not files:
        raise RuntimeError(
            f"no Python files under {', '.join(str(r) for r in roots)} — "
            f"refusing to report a count from an empty scan"
        )

    found: list[Violation] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError, UnicodeDecodeError:
            continue  # not ours to parse; ruff owns syntax
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not node.name.startswith("_compute_"):
                continue
            missing = read_keys(node) - declared_keys(node)
            found.extend(
                Violation(_display(path), node.lineno, node.name, key)
                for key in sorted(missing)
            )
    return sorted(found, key=lambda v: (v.key, v.file, v.line))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--key", help="restrict the report to one context key")
    parser.add_argument(
        "--roots", nargs="+", help="scan these paths instead of odoo/ and addons/"
    )
    parser.add_argument(
        "--top", type=int, default=30, help="offenders to list (0 = all)"
    )
    args = parser.parse_args(argv)

    roots = [Path(r).resolve() for r in args.roots] if args.roots else None
    try:
        found = measure(roots)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.key:
        found = [v for v in found if v.key == args.key]

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(v) for v in found], indent=2))
        return 0

    print("Computes reading context they do not declare (@api.depends_context)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(f"  {item}")
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)

    by_key = collections.Counter(v.key for v in found)
    print(f"\n{len(found)} undeclared context read(s)\n")
    for key, n in by_key.most_common():
        print(f"    {key:<10}{n:>5}")

    print("\nRatchet this number:")
    print("  python tooling/architecture/compute_context_deps.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py computectx --count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
