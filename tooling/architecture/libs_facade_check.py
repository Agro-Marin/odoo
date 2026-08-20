#!/usr/bin/env python3


from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from functools import cache, lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0004"

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="libs_facade_check")
LIBS = REPO_ROOT / "odoo" / "libs"

SCANNED_TREES: tuple[Path, ...] = (
    REPO_ROOT / "odoo" / "addons",
    REPO_ROOT / "addons",
    REPO_ROOT / "odoo" / "tools",
    REPO_ROOT / "odoo" / "orm",
    REPO_ROOT / "odoo" / "http",
    REPO_ROOT / "odoo" / "modules",
    REPO_ROOT / "odoo" / "service",
    REPO_ROOT / "odoo" / "db",
    REPO_ROOT / "odoo" / "cli",
    REPO_ROOT / "odoo" / "tests",
    REPO_ROOT / "odoo" / "_monkeypatches",
    REPO_ROOT / "odoo" / "upgrade_code",
    REPO_ROOT / "odoo" / "api",
    REPO_ROOT / "odoo" / "fields",
    REPO_ROOT / "odoo" / "models",
)

ADDON_TREES: tuple[Path, ...] = SCANNED_TREES[:2]


@dataclass(frozen=True)
class Known:
    path: str
    module: str
    reason: str


KNOWN_VIOLATIONS: tuple[Known, ...] = (
    Known(
        "odoo/addons/test_mimetypes/tests/test_guess_mimetypes.py",
        "odoo.libs.filesystem.mimetypes",
        "Imports _odoo_guess_mimetype, the pure-Python fallback deliberately "
        "kept out of the odoo.libs.filesystem façade: this suite exists to test "
        "it against the python-magic path, so it must name the implementation.",
    ),
    Known(
        "odoo/addons/test_http/utils.py",
        "odoo.libs._vendor.sessions",
        "SessionStore from the vendored werkzeug session code. _vendor is "
        "third-party source kept verbatim; giving it a curated façade would "
        "imply a stability promise the vendor makes, not us.",
    ),
    Known(
        "odoo/tools/sass_embedded.py",
        "odoo.libs._vendor.embedded_sass_pb2",
        "Generated protobuf bindings for the Dart Sass embedded protocol. Same "
        "reasoning as the other _vendor entry: the file is generated, not "
        "authored, and re-exporting its symbols through an area would put a "
        "curated name on a protobuf-versioned surface.",
    ),
    Known(
        "odoo/tools/mail.py",
        "odoo.libs.email.parsing",
        "_normalize_email, deliberately private: the public entry points are "
        "email_normalize/email_normalize_all, and tools/mail.py needs the "
        "un-guarded inner form. Exporting it would promote an implementation "
        "detail to API for one caller.",
    ),
    Known(
        "odoo/tools/template_inheritance.py",
        "odoo.libs.xml.template_inheritance",
        "_compile_xpath, deliberately private. tools/template_inheritance.py "
        "wraps the area's public apply_inheritance_specs/locate_node (both "
        "imported from the area) and additionally needs the raw xpath "
        "compiler to translate lxml errors into ValidationError.",
    ),
    Known(
        "odoo/http/wrappers.py",
        "odoo.libs._vendor.useragents",
        "UserAgent from the vendored werkzeug user-agent code. Same reasoning as "
        "the other _vendor entries: third-party source kept verbatim, with no "
        "curated area façade to promise stability the vendor does not.",
    ),
    Known(
        "odoo/orm/tests/test_sorted_multi_key.py",
        "odoo.libs._field_access._fallback",
        "Imports the pure-Python sort_ids_by_values fallback alongside the area's "
        "fast path to assert parity between them — the same test-the-"
        "implementation pattern as the test_guess_mimetypes entry, so it must "
        "name the fallback the area deliberately does not export.",
    ),
    Known(
        "odoo/http/tests/test_session_store.py",
        "odoo.libs._vendor.sessions",
        "_fs_transaction_suffix from the vendored werkzeug session store, needed "
        "to assert the tmp-file vacuum reaps orphans. Same _vendor reasoning as "
        "test_http/utils.py: the vendored source has no curated area façade.",
    ),
)


@dataclass
class Violation:
    path: str
    module: str
    lineno: int
    area: str


@dataclass
class Report:
    new: list[Violation] = field(default_factory=list)
    known: list[Violation] = field(default_factory=list)
    areas: set[str] = field(default_factory=set)
    scanned: int = 0

    @property
    def ok(self) -> bool:
        return not self.new


@lru_cache(maxsize=1)
def areas() -> frozenset[str]:

    found = {"odoo.libs"}
    for child in LIBS.iterdir():
        if child.name.startswith("__") or child.name == "tests":
            continue
        if child.is_dir() and (child / "__init__.py").is_file():
            found.add(f"odoo.libs.{child.name}")
        elif child.suffix == ".py":
            found.add(f"odoo.libs.{child.stem}")
    return frozenset(found)


@cache
def module_exists(dotted: str) -> bool:
    rel = dotted.removeprefix("odoo.libs.").split(".")
    base = LIBS.joinpath(*rel)
    return (base / "__init__.py").is_file() or base.with_suffix(".py").is_file()


def imported_modules(tree: ast.AST) -> list[tuple[str, int]]:

    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if not node.level and node.module and node.module.startswith("odoo.libs"):
                out.append((node.module, node.lineno))
        elif isinstance(node, ast.Import):
            out.extend(
                (alias.name, node.lineno)
                for alias in node.names
                if alias.name.startswith("odoo.libs")
            )
    return out


def _is_known(path: str, module: str) -> bool:
    return any(k.path == path and k.module == module for k in KNOWN_VIOLATIONS)


def check(files: list[Path] | None = None) -> Report:
    report = Report(areas=set(areas()))
    if files is None:
        files = [
            p
            for tree in SCANNED_TREES
            if tree.is_dir()
            for p in sorted(tree.rglob("*.py"))
            if "__pycache__" not in p.parts
        ]
    # Refuse a scan that reached no file rather than report the façade clean.
    # `SCANNED_TREES` is filtered by `is_dir()`, so an emptied or mis-rooted
    # checkout yielded no files and printed a ✓ -- indistinguishable from a tree
    # where every addon imports areas correctly. Only the no-argument form is
    # guarded: the self-test legitimately passes one probe file.
    if not files:
        raise SystemExit(
            "libs_facade_check: no Python sources under "
            f"{', '.join(str(t) for t in SCANNED_TREES)} — the scan found no "
            "inputs; refusing to report the façade clean."
        )
    allowed = areas()
    for path in files:
        report.scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover
            print(f"warning: could not parse {path}: {exc}", file=sys.stderr)
            continue
        for module, lineno in imported_modules(tree):
            if module in allowed:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            area = ".".join(module.split(".")[:3])
            v = Violation(rel, module, lineno, area)
            (report.known if _is_known(rel, module) else report.new).append(v)
    return report


def _render(report: Report) -> str:
    lines = [
        "odoo.libs façade boundary",
        "=" * 64,
        f"addon files scanned: {report.scanned}",
        f"public areas of odoo.libs: {len(report.areas)}",
    ]
    if report.new:
        lines.append(f"\n{len(report.new)} NEW leaf-module import(s):")
        lines.extend(
            f"  {v.path}:{v.lineno}\n"
            f"      imports {v.module}\n"
            f"      use the area instead: {v.area}"
            for v in report.new
        )
    if report.known:
        lines.append(f"\n{len(report.known)} known import(s) tolerated (tracked debt):")
        lines.extend(
            f"  {v.path}:{v.lineno}  {v.module}"
            for v in sorted(report.known, key=lambda x: (x.path, x.lineno))
        )
    lines.append("")
    lines.append(
        "Addon code imports odoo.libs areas, not their internals. ✓"
        if report.ok
        else "FAILED: addon code reached past the odoo.libs façade."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate the odoo.libs façade.")
    parser.add_argument("--check", action="store_true", help="CI mode: exit 1 on drift")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    report = check()
    if args.json:
        print(
            json.dumps(
                {
                    "ok": report.ok,
                    "scanned": report.scanned,
                    "areas": sorted(report.areas),
                    "new": [
                        {"path": v.path, "line": v.lineno, "module": v.module}
                        for v in report.new
                    ],
                    "known": len(report.known),
                },
                indent=2,
            )
        )
    else:
        print(_render(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
