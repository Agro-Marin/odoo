"""Writes of ``product_uom_qty`` on a sale or purchase order line.

``product_qty`` and ``product_uom_qty`` swapped meanings in this fork, and both
names survived (`doc/coding_guidelines.rst` Appendix A). ``product_qty`` is the
ordered quantity **in the line's own unit** and is the writable one;
``product_uom_qty`` is that quantity converted to the product's **reference**
unit, computed, stored and ``readonly``.

Writing ``product_uom_qty`` does not raise. It does one of two wrong things::

    create({..., "product_uom_qty": 10})   value discarded, product_qty
                                            falls back to its default of 1
    line.write({"product_uom_qty": 3})     value lands in the column while
                                            product_qty keeps its old value

The first is why a test that says it orders ten passes while ordering one — the
default absorbs it, and nothing downstream can tell the difference. The second
leaves the record self-contradictory: 1 in the line's unit, 3 in the reference
unit, for a product whose two units are the same, until some dependency
recomputes and one of the numbers changes under whoever is reading it.

Both were live across the mrp ring. ``sale_mrp_margin`` sold three boxes of ten
and delivered one; ``sale_mrp_renting``'s four failures were seven ``write``
calls desynchronising one rental line; ``sale_stock_margin``'s helper made every
line quantity 1, which is the whole of the eight failures `CLAUDE.md` §4
attributed to "the order layer". Model code had it too: ``sale_mrp`` and
``purchase_mrp`` fed the reference-unit number to a conversion that declares its
input to be in ``product_uom_id``.

**What is counted.** Any ``product_uom_qty`` key written into a dict that is
recognisably an order line — a ``create``/``write`` on ``sale.order.line`` or
``purchase.order.line``, a dict carrying ``order_id``, a dict under a
``line_ids``/``order_line`` command — and any assignment to
``<an order-line expression>.product_uom_qty``. ``stock.move.product_uom_qty`` is a
real, writable field and is not counted; most matches in mrp's own tests are
moves, which is why the target has to be recognised rather than the name alone.

**A value of 1 is counted too**, though it happens to be inert: the default
absorbs it, so the record comes out right by luck. A rule with "unless the value
is 1" in it is not a rule anyone can apply, and the line still says the wrong
thing about which field holds the ordered quantity.

**Why a ratchet and not a raise.** Refusing the write outright is where this
should end — that is what every other rename in Appendix A does, and a silent
half-write is exactly the failure mode the raise exists to prevent. It cannot
land yet: the workspace carries hundreds of these, most in modules whose suites
would have to be re-run and re-read one by one. So the count is floored first,
so no new one lands, and the floor is driven down per module until the raise
costs nothing.

Scope note: like ``naming_vocabulary.py`` this measures the ``odoo`` checkout by
default, because that is what CI checks out. ``--roots`` measures a sibling repo;
those have no baseline of their own (`CLAUDE.md` §9.4).
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

from _repo_root import find_odoo_root

#: The argument is ADR-0033's, one rule over: a load-bearing naming rule with
#: a backlog too large to block on is counted and ratcheted instead. That
#: record is scoped to guidelines §2.4's abolished verbs, and this enforces
#: Appendix A, so it is not cited -- the omission is pinned in
#: test_gate_adr_coverage.UNRECORDED_GATES, which is where it stays visible.
ADR = "unrecorded"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="order_line_qty")

FIELD = "product_uom_qty"
CANONICAL = "product_qty"

#: models whose ``create``/``write`` makes any ``product_uom_qty`` key an offence
LINE_MODELS = frozenset({"sale.order.line", "purchase.order.line"})

#: one2many commands whose payload dicts are order lines
LINE_COMMANDS = frozenset({"line_ids", "order_line"})

#: a key that identifies a bare dict as an order line rather than a stock move
LINE_MARKER = "order_id"

#: the attribute an order-line expression ends in (``order.line_ids``)
LINE_ATTRS = frozenset({"line_ids", "order_line"})

#: names a bare order-line variable goes by (``sol``, ``sol_2``, ``so_line``)
LINE_NAMES = re.compile(r"^(sol|so_line|po_line|sale_line|purchase_line)\d*(_\w+)?$")


def _is_order_line_expr(node: ast.AST) -> bool:
    """Does this expression evaluate to order lines rather than stock moves?

    Deliberately narrow. Matching a substring anywhere in the source — which is
    what the first draft did — makes ``sol`` match ``console`` and ``resolve``,
    and a gate that over-counts is one people learn to argue with rather than
    fix.
    """
    if isinstance(node, ast.Attribute):
        return node.attr in LINE_ATTRS or _is_order_line_expr(node.value)
    if isinstance(node, ast.Name):
        return bool(LINE_NAMES.match(node.id))
    if isinstance(node, ast.Subscript):
        return _is_order_line_expr(node.value)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        # `order.line_ids.filtered(...)` is still order lines
        return node.func.attr in ("filtered", "sorted", "browse") and (
            _is_order_line_expr(node.func.value)
        )
    return False


@dataclass(frozen=True)
class Write:
    path: str
    line: int
    kind: str
    value: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.kind}  {FIELD} = {self.value}"


def _string_keys(node: ast.Dict) -> set[str]:
    return {
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _value_for(node: ast.Dict, name: str) -> str:
    for key, value in zip(node.keys, node.values, strict=False):
        if isinstance(key, ast.Constant) and key.value == name:
            return ast.unparse(value)
    return "?"


def _payload_dicts(call: ast.Call):
    """The dicts a ``create``/``write`` call is given, one or many."""
    for arg in call.args:
        if isinstance(arg, ast.Dict):
            yield arg
        elif isinstance(arg, (ast.List, ast.Tuple)):
            for element in arg.elts:
                if isinstance(element, ast.Dict):
                    yield element


def _subscript_model(node: ast.AST) -> str | None:
    """``env["sale.order.line"]`` -> ``sale.order.line``."""
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        value = node.slice.value
        if isinstance(value, str):
            return value
    return None


def _scan(path: Path, rel: str, out: dict[tuple[str, int], Write]) -> None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError, UnicodeDecodeError:
        return

    def record(lineno: int, kind: str, value: str) -> None:
        out.setdefault((rel, lineno), Write(rel, lineno, kind, value))

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("create", "write")
        ):
            model = _subscript_model(node.func.value)
            for payload in _payload_dicts(node):
                keys = _string_keys(payload)
                if FIELD not in keys:
                    continue
                if (
                    model in LINE_MODELS
                    or LINE_MARKER in keys
                    or _is_order_line_expr(node.func.value)
                ):
                    record(payload.lineno, node.func.attr, _value_for(payload, FIELD))

        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if not (isinstance(key, ast.Constant) and key.value in LINE_COMMANDS):
                    continue
                for inner in ast.walk(value):
                    if isinstance(inner, ast.Dict) and FIELD in _string_keys(inner):
                        record(inner.lineno, "create", _value_for(inner, FIELD))

        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not (isinstance(target, ast.Attribute) and target.attr == FIELD):
                    continue
                if _is_order_line_expr(target.value):
                    record(target.lineno, "assign", ast.unparse(node.value))


def default_roots() -> list[Path]:
    return [ROOT / "addons", ROOT / "odoo" / "addons"]


def measure(roots: list[Path] | None = None) -> list[Write]:
    roots = roots or default_roots()
    missing = [root for root in roots if not root.is_dir()]
    if missing:
        raise RuntimeError(
            "no such directory: " + ", ".join(str(root) for root in missing)
        )
    found: dict[tuple[str, int], Write] = {}
    scanned = 0
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            scanned += 1
            try:
                rel = str(path.relative_to(root.parent))
            except ValueError:
                rel = str(path)
            _scan(path, rel, found)
    if not scanned:
        # A count of zero over a tree with no Python in it is the same number a
        # clean tree reports, and the ratchet cannot tell them apart. Refuse.
        raise RuntimeError(
            "no Python source under "
            + ", ".join(str(root) for root in roots)
            + " — refusing to report a count measured over nothing"
        )
    return [found[key] for key in sorted(found)]


def _module_of(write: Write) -> str:
    parts = write.path.split("/")
    return "/".join(parts[:2]) if len(parts) > 1 else write.path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--roots", nargs="+", help="scan these paths instead of the odoo checkout"
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

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(w) for w in found], indent=2))
        return 0

    print(f"Order-line writes of `{FIELD}` (should be `{CANONICAL}`)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for write in shown:
        print(f"  {write}")
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)

    inert = sum(1 for w in found if w.kind == "create" and w.value in ("1", "1.0"))
    print(f"\n{len(found)} write(s) of `{FIELD}` on an order line")
    print(
        f"  {len(found) - inert} change behaviour: a create of any other quantity "
        f"silently\n  becomes 1, and every `write` desynchronises the two fields."
    )
    print(
        f"  {inert} are create(s) of 1, which the default absorbs — inert today, "
        f"and\n  still the wrong field."
    )

    by_module = collections.Counter(_module_of(w) for w in found)
    print("\nBy module:\n")
    for module, count in by_module.most_common(None if args.top == 0 else args.top):
        print(f"  {count:4d}  {module}")
    if len(by_module) > (args.top or len(by_module)):
        print(f"  ... and {len(by_module) - args.top} more (--top 0 for all)")

    print("\nRatchet this number:")
    print("  python tooling/architecture/order_line_qty.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py orderlineqty --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())
