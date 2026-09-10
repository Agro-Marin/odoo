from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _repo_root import find_odoo_root

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ast_cache

ROOT = find_odoo_root(Path(__file__).resolve(), tool="supplierinfo_write_authority")

MODEL = "product.supplierinfo"
PRICE_FIELDS = frozenset({"price", "min_qty", "date_start", "date_end", "discount"})
RELATIONS = frozenset(
    {"seller_ids", "variant_seller_ids", "supplier_info_ids", "supplierinfo_ids"}
)
PASSTHROUGH = frozenset(
    {"sudo", "with_company", "with_context", "with_user", "with_env", "filtered"}
)
SELLER_NAMES = re.compile(
    r"^(seller|supplier|supplierinfo|supplier_info)s?(_\w+)?$", re.IGNORECASE
)
SKIPPED_DIRS = frozenset({"tests", "demo", "migrations", "upgrades", "__pycache__"})

AUTHORITIES: dict[tuple[str, str], str] = {
    (
        "purchase",
        "PurchaseOrder._create_supplier_to_product",
    ): "confirming an order records a new vendor at the price the buyer agreed",
    (
        "purchase_requisition",
        "PurchaseRequisitionLine._create_supplier_info",
    ): "a blanket order projects its line onto the row that prices it, until "
    "purchase_contract replaces the projection",
    (
        "purchase_requisition",
        "PurchaseRequisitionLine.write",
    ): "the same projection, following a price edit on a confirmed agreement",
}


@dataclass(frozen=True)
class Write:
    path: str
    line: int
    module: str
    function: str
    shape: str
    fields: str

    def __str__(self) -> str:
        return (
            f"{self.path}:{self.line}  {self.module}  {self.function}  "
            f"[{self.shape}]  {self.fields}"
        )


def _string_keys(node: ast.Dict) -> set[str]:
    return {
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _strip_passthrough(node: ast.AST) -> ast.AST:
    while (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in PASSTHROUGH
    ):
        node = node.func.value
    return node


def _is_model_lookup(node: ast.AST) -> bool:
    node = _strip_passthrough(node)
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == MODEL
    )


def _holds_sellers(node: ast.AST, aliases: set[str]) -> bool:
    node = _strip_passthrough(node)
    if _is_model_lookup(node):
        return True
    if isinstance(node, ast.Attribute):
        return node.attr in RELATIONS
    if isinstance(node, ast.Name):
        return node.id in aliases or bool(SELLER_NAMES.match(node.id))
    return False


def _price_dicts(node: ast.AST):
    for inner in ast.walk(node):
        if isinstance(inner, ast.Dict):
            hit = _string_keys(inner) & PRICE_FIELDS
            if hit:
                yield inner, hit


def _payload(call: ast.Call) -> tuple[set[str], bool]:
    fields: set[str] = set()
    visible = False
    for arg in [*call.args, *(kw.value for kw in call.keywords)]:
        for _, hit in _price_dicts(arg):
            fields |= hit
        if isinstance(arg, ast.Dict) or (
            isinstance(arg, ast.List | ast.Tuple)
            and all(isinstance(element, ast.Dict) for element in arg.elts)
        ):
            visible = True
    return fields, visible


def _module_of(path: Path, root: Path) -> str:
    for parent in path.parents:
        if (parent / "__manifest__.py").is_file():
            return parent.name
        if parent == root:
            break
    return path.parent.name


class _Scanner(ast.NodeVisitor):
    def __init__(self, rel: str, module: str) -> None:
        self.rel = rel
        self.module = module
        self.scope: list[str] = []
        self.aliases: list[set[str]] = [set()]
        self.found: dict[int, Write] = {}

    def _record(self, line: int, shape: str, fields: set[str] | str) -> None:
        label = fields if isinstance(fields, str) else ",".join(sorted(fields))
        function = ".".join(self.scope) or "<module>"
        self.found.setdefault(
            line, Write(self.rel, line, self.module, function, shape, label)
        )

    def _enter(self, node, name: str) -> None:
        self.scope.append(name)
        self.aliases.append(set(self.aliases[-1]))
        self.generic_visit(node)
        self.aliases.pop()
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and _is_model_lookup(node.value):
                self.aliases[-1].add(target.id)
            if not isinstance(target, ast.Attribute):
                continue
            if target.attr in PRICE_FIELDS and _holds_sellers(
                target.value, self.aliases[-1]
            ):
                self._record(target.lineno, "assign", target.attr)
            elif target.attr in RELATIONS:
                fields = set().union(*(hit for _, hit in _price_dicts(node.value)))
                if fields:
                    self._record(target.lineno, f"assign {target.attr}", fields)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in ("create", "write")
            and _holds_sellers(func.value, self.aliases[-1])
        ):
            fields, visible = _payload(node)
            receiver = _strip_passthrough(func.value)
            opaque_target = _is_model_lookup(func.value) or (
                isinstance(receiver, ast.Name) and receiver.id in self.aliases[-1]
            )
            if fields:
                self._record(node.lineno, func.attr, fields)
            elif not visible and opaque_target:
                self._record(node.lineno, func.attr, "payload not visible")
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values, strict=False):
            if isinstance(key, ast.Constant) and key.value in RELATIONS:
                for inner, hit in _price_dicts(value):
                    self._record(inner.lineno, f"command under {key.value}", hit)
        self.generic_visit(node)


def default_roots() -> list[Path]:
    return [ROOT / "addons", ROOT / "odoo" / "addons"]


def measure(roots: list[Path] | None = None) -> list[Write]:
    roots = roots or default_roots()
    missing = [root for root in roots if not root.is_dir()]
    if missing:
        raise RuntimeError(
            "no such directory: " + ", ".join(str(root) for root in missing)
        )
    found: list[Write] = []
    scanned = 0
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if SKIPPED_DIRS & set(path.relative_to(root).parts):
                continue
            scanned += 1
            scanner = _Scanner(
                str(path.relative_to(root.parent)), _module_of(path, root)
            )
            scanner.visit(_ast_cache.parse_file(path))
            found.extend(scanner.found[line] for line in sorted(scanner.found))
    if not scanned:
        raise RuntimeError(
            "no Python source under "
            + ", ".join(str(root) for root in roots)
            + " — refusing to report a count measured over nothing"
        )
    return found


def split(found: list[Write]) -> tuple[list[Write], list[tuple[str, str]]]:
    unauthorised = [w for w in found if (w.module, w.function) not in AUTHORITIES]
    writing = {(w.module, w.function) for w in found}
    stale = [key for key in AUTHORITIES if key not in writing]
    return unauthorised, stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--roots", nargs="+", help="scan these paths instead of the odoo checkout"
    )
    args = parser.parse_args(argv)

    roots = [Path(r).resolve() for r in args.roots] if args.roots else None
    try:
        found = measure(roots)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    unauthorised, stale = split(found)
    if args.roots:
        stale = []

    if args.count:
        print(len(unauthorised) + len(stale))
        return 0
    if args.json:
        print(
            json.dumps(
                {
                    "unauthorised": [asdict(w) for w in unauthorised],
                    "stale_authorities": [list(key) for key in stale],
                },
                indent=2,
            )
        )
        return 0

    print(f"Writes of {', '.join(sorted(PRICE_FIELDS))} on {MODEL}")
    print("=" * 72)
    for write in found:
        mark = "ok " if (write.module, write.function) in AUTHORITIES else "NEW"
        print(f"  {mark} {write}")
    for module, function in stale:
        print(f"  STALE authority {module} {function}: it no longer writes")
    print("-" * 72)
    print(
        f"{len(unauthorised)} unauthorised write(s), {len(stale)} stale authority "
        "entr(y/ies). Hard zero: add a site to AUTHORITIES with its reason, or route "
        "it through the authority that owns the price."
    )
    return 1 if unauthorised or stale else 0


if __name__ == "__main__":
    sys.exit(main())
