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

ADR = "unrecorded"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="order_line_qty")

FIELD = "product_uom_qty"
CANONICAL = "product_qty"

LINE_MODELS = frozenset({"sale.order.line", "purchase.order.line"})

LINE_COMMANDS = frozenset({"line_ids", "order_line"})

LINE_MARKER = "order_id"

LINE_ATTRS = frozenset({"line_ids", "order_line"})

LINE_NAMES = re.compile(r"^(sol|so_line|po_line|sale_line|purchase_line)\d*(_\w+)?$")


def _is_order_line_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr in LINE_ATTRS or _is_order_line_expr(node.value)
    if isinstance(node, ast.Name):
        return bool(LINE_NAMES.match(node.id))
    if isinstance(node, ast.Subscript):
        return _is_order_line_expr(node.value)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
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
    for arg in call.args:
        if isinstance(arg, ast.Dict):
            yield arg
        elif isinstance(arg, (ast.List, ast.Tuple)):
            for element in arg.elts:
                if isinstance(element, ast.Dict):
                    yield element


def _subscript_model(node: ast.AST) -> str | None:
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
