import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0029"

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="worker_thread_surface_check")
CORE = REPO_ROOT / "odoo"

ACCESSOR_REL = "odoo/libs/worker_thread.py"

KNOWN_RAW_SURFACE: frozenset[tuple[str, str]] = frozenset()


def _protocol_attrs() -> frozenset[str]:

    src = (CORE / "libs" / "worker_thread.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "WorkerThread":
            return frozenset(
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            )
    raise RuntimeError(
        "WorkerThread Protocol not found in odoo/libs/worker_thread.py; "
        "the worker-thread surface gate cannot determine its attribute set."
    )


PROTOCOL_ATTRS: frozenset[str] = _protocol_attrs()


def _is_current_thread_call(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "current_thread":
        return True
    return isinstance(func, ast.Name) and func.id == "current_thread"


@dataclass(frozen=True)
class Reach:
    attr: str
    path: str
    lineno: int

    @property
    def pair(self) -> tuple[str, str]:
        return (self.path, self.attr)


@dataclass
class Report:
    reaches: list[Reach] = field(default_factory=list)
    added: set[tuple[str, str]] = field(default_factory=set)
    removed: set[tuple[str, str]] = field(default_factory=set)

    @property
    def pairs(self) -> set[tuple[str, str]]:
        return {r.pair for r in self.reaches}

    @property
    def ok(self) -> bool:
        return not self.added and not self.removed


class _WorkerThreadCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.hits: list[tuple[str, int]] = []

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.generic_visit(node)
        if node.attr in PROTOCOL_ATTRS and _is_current_thread_call(node.value):
            self.hits.append((node.attr, node.lineno))

    def visit_Call(self, node: ast.Call) -> None:
        self.generic_visit(node)
        func = node.func
        if (
            isinstance(func, ast.Name)
            and func.id in ("getattr", "hasattr", "delattr")
            and len(node.args) >= 2
            and _is_current_thread_call(node.args[0])
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in PROTOCOL_ATTRS
        ):
            self.hits.append((node.args[1].value, node.lineno))


def iter_scope_files() -> list[Path]:
    out: list[Path] = []
    addons = CORE / "addons"
    for p in sorted(CORE.rglob("*.py")):
        parts = p.parts
        if "tests" in parts or "__pycache__" in parts or p.name.startswith("test_"):
            continue
        if addons in p.parents:
            continue
        if p.relative_to(REPO_ROOT).as_posix() == ACCESSOR_REL:
            continue
        out.append(p)
    return out


def check(files: list[Path] | None = None) -> Report:
    report = Report()
    for path in files if files is not None else iter_scope_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover
            print(f"warning: could not parse {path}: {exc}", file=sys.stderr)
            continue
        collector = _WorkerThreadCollector()
        collector.visit(tree)
        try:
            rel = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = path.as_posix()
        for attr, lineno in collector.hits:
            report.reaches.append(Reach(attr, rel, lineno))
    report.added = report.pairs - KNOWN_RAW_SURFACE
    report.removed = KNOWN_RAW_SURFACE - report.pairs
    return report


def _render(report: Report) -> str:
    lines = [
        "Framework → worker-thread bookkeeping surface (inline current_thread)",
        "=" * 68,
        (
            "attributes tracked (from WorkerThread Protocol): "
            f"{', '.join(sorted(PROTOCOL_ATTRS))}"
        ),
        f"inline raw access sites: {len(report.reaches)}",
        "",
    ]
    for r in sorted(report.reaches, key=lambda r: (r.path, r.lineno)):
        marker = "  NEW" if r.pair in report.added else ""
        lines.append(f"  {r.path}:{r.lineno}  .{r.attr}{marker}")
    if report.added:
        lines.append("")
        lines.append("NEW inline raw accesses (use current_worker_thread() instead):")
        for path, attr in sorted(report.added):
            sites = [
                f"{r.path}:{r.lineno}" for r in report.reaches if r.pair == (path, attr)
            ]
            lines.append(f"  + {path} .{attr}   {', '.join(sites)}")
    if report.removed:
        lines.append("")
        lines.append("Baseline entries no longer present (commit the conversion):")
        lines.extend(f"  - {path} .{attr}" for path, attr in sorted(report.removed))
    lines.append("-" * 68)
    if report.ok:
        lines.append("Worker-thread surface matches the acknowledged set. ✓")
    else:
        lines.append("FAILED: worker-thread surface drifted from the baseline.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate the framework's untyped reach into worker-thread state."
    )
    parser.add_argument("--check", action="store_true", help="CI mode: exit 1 on drift")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--print-baseline",
        action="store_true",
        help="print the current (path, attr) pairs as a Python literal",
    )
    args = parser.parse_args(argv)

    report = check()

    if args.print_baseline:
        for path, attr in sorted(report.pairs):
            print(f'        ("{path}", "{attr}"),')
        return 0
    if args.json:
        print(
            json.dumps(
                {
                    "sites": sorted([r.path, r.lineno, r.attr] for r in report.reaches),
                    "added": sorted(list(p) for p in report.added),
                    "removed": sorted(list(p) for p in report.removed),
                    "ok": report.ok,
                },
                indent=2,
            )
        )
        return 0 if report.ok else 1

    print(_render(report))
    if args.check:
        return 0 if report.ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
