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

Three keys, each with a demonstrated failure behind it:

===================================  ===============
read in the body                     key it needs
===================================  ===============
``env.user`` / ``env.uid``           ``uid``
``_get_guest_from_context``          ``guest``
``get_lang``, the ``format_*``       ``lang``
helpers that take an ``env``, and
``_description_selection``
===================================  ===============

``lang`` was added after a compute shipped the defect in a file where the gate
could not see it. ``mrp.workcenter.kanban_dashboard_graph`` reaches ``get_lang``
twice through its week-range helper -- once for the locale of the labels and
once for ``week_start``, which decides the bucket *boundaries* -- and declared
nothing. Two readers in one transaction::

    en first -> en ['9 - 15 Aug',   'This Week',     '23 - 29 Aug', ...]
             -> fr ['9 - 15 Aug',   'This Week',     '23 - 29 Aug', ...]
    fr first -> fr ['10 - 16 aout', 'Cette semaine', '24 - 30 aout', ...]
             -> en ['10 - 16 aout', 'Cette semaine', '24 - 30 aout', ...]

The ``env.user`` read that would have caught it sits one call deep inside
``get_lang``, and this check is deliberately syntactic, so the file scored zero.
Naming the helpers rather than following them into ``odoo.tools`` keeps it that
way.

Worth saying why a compute needs the key at all when translated *fields* already
carry ``lang`` in theirs: for a computed field ``Field.get_depends`` reads
``depends_context`` from the compute methods alone. A *related* field inherits
its chain's keys; **a compute inherits nothing** from the fields it reads. So a
compute that resolves the language, or reads a translated field, holds one cache
entry for the whole transaction unless it says so.

``_description_selection`` reduced to its keys is not a language read -- the keys
are the same string in every language -- so ``list(dict(...))`` and
``dict(...).keys()`` are excluded. Measured, that is 2 of the 12 occurrences
under a ``_compute_``; the other 10 build a label lookup and are real.

``format_datetime`` additionally resolves ``env.user.tz``. A ``tz`` gate is the
next move on this list and a separate one: different key, different argument
about which computes may legitimately read it.

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
import _sources
from _repo_root import find_odoo_root

ADR = "unrecorded"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="compute_context_deps")
SCAN_ROOTS = ("odoo", "addons")

ENV_READS = {
    "uid": ("user", "uid"),
}
CALL_READS = {
    "guest": ("_get_guest_from_context",),
    "lang": (
        "get_lang",
        "format_amount",
        "format_date",
        "format_datetime",
        "format_list",
        "_description_selection",
    ),
}

KEY_ONLY_WRAPPERS = ("list", "keys", "tuple", "set", "sorted")


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    method: str
    key: str

    def __str__(self) -> str:
        return f"{self.key:<8} {self.file}:{self.line}  {self.method}"


def _python_files(roots: list[Path]) -> list[Path]:
    return sorted(
        p
        for root in roots
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and not _sources.is_test_path(p)
    )


def declared_keys(node: ast.FunctionDef) -> set[str]:
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


def _parents(node: ast.FunctionDef) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(node)
        for child in ast.iter_child_nodes(parent)
    }


def _reads_labels(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> bool:
    wrapper = parents.get(call)
    if not (isinstance(wrapper, ast.Call) and _called_name(wrapper) == "dict"):
        return True
    outer = parents.get(wrapper)
    if isinstance(outer, ast.Call) and _called_name(outer) in KEY_ONLY_WRAPPERS:
        return False
    return not (isinstance(outer, ast.Attribute) and outer.attr in KEY_ONLY_WRAPPERS)


def _called_name(call: ast.Call) -> str:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def read_keys(node: ast.FunctionDef) -> set[str]:
    keys: set[str] = set()
    parents = _parents(node)
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute):
            value = sub.value
            reads_env = (isinstance(value, ast.Attribute) and value.attr == "env") or (
                isinstance(value, ast.Name) and value.id == "env"
            )
            if reads_env:
                for key, attrs in ENV_READS.items():
                    if sub.attr in attrs:
                        keys.add(key)
        elif isinstance(sub, ast.Call):
            called = _called_name(sub)
            for key, names in CALL_READS.items():
                if called not in names:
                    continue
                if called == "_description_selection" and not _reads_labels(
                    sub, parents
                ):
                    continue
                keys.add(key)
    return keys


def measure(roots: list[Path] | None = None) -> list[Violation]:
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
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not node.name.startswith("_compute_"):
                continue
            missing = read_keys(node) - declared_keys(node)
            found.extend(
                Violation(_sources.display(path, ROOT), node.lineno, node.name, key)
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
