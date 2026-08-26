#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import contextlib
import difflib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sources
import doc_measured
from _repo_root import find_odoo_root

ADR = "unrecorded"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="translation_catalog")

ADDON_ROOTS = (ROOT / "odoo" / "addons", ROOT / "addons")

GETTEXT_NAMES = frozenset({"_", "_lt"})


@dataclass(frozen=True)
class Cost:
    previous: str
    ratio: float
    translated: int
    catalogues: int
    languages: list[str]


@dataclass(frozen=True)
class Unresolved:
    module: str
    file: str
    line: int
    source: str

    def __str__(self) -> str:
        text = self.source if len(self.source) <= 72 else self.source[:69] + "..."
        return f"  {self.file}:{self.line}  {text!r}"


def iter_modules(roots: tuple[Path, ...] = ADDON_ROOTS) -> list[tuple[str, Path, Path]]:
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        for module_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            pot = module_dir / "i18n" / f"{module_dir.name}.pot"
            if pot.is_file():
                found.append((module_dir.name, module_dir, pot))
    return found


def read_msgids(pot: Path) -> set[str]:
    msgids: set[str] = set()
    chunks: list[str] = []
    collecting = False

    def flush() -> None:
        if not chunks:
            return
        with contextlib.suppress(SyntaxError, ValueError):
            msgids.add(ast.literal_eval(" ".join(chunks)))
        chunks.clear()

    for raw in pot.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("msgid "):
            flush()
            chunks.append(line[len("msgid ") :])
            collecting = True
        elif collecting and line.startswith('"'):
            chunks.append(line)
        else:
            flush()
            collecting = False
    flush()
    return msgids


def read_translations(po: Path) -> dict[str, str]:
    pairs: dict[str, str] = {}
    key: str | None = None
    chunks: list[str] = []
    mode: str | None = None

    def flush() -> None:
        nonlocal key, chunks, mode
        if mode == "id" and chunks:
            try:
                key = ast.literal_eval(" ".join(chunks))
            except SyntaxError, ValueError:
                key = None
        elif mode == "str" and chunks and key is not None:
            with contextlib.suppress(SyntaxError, ValueError):
                pairs[key] = ast.literal_eval(" ".join(chunks))
            key = None
        chunks = []

    for raw in po.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("msgid "):
            flush()
            mode, chunks = "id", [line[len("msgid ") :]]
        elif line.startswith("msgstr "):
            flush()
            mode, chunks = "str", [line[len("msgstr ") :]]
        elif line.startswith('"') and mode:
            chunks.append(line)
        else:
            flush()
            mode = None
    flush()
    return pairs


REWORD_RATIO = 0.6


def reword_cost(source: str, module_dir: Path, msgids: set[str]) -> Cost | None:
    near = difflib.get_close_matches(source, msgids, n=1, cutoff=REWORD_RATIO)
    if not near:
        return None
    previous = near[0]
    catalogues = sorted((module_dir / "i18n").glob("*.po"))
    translated = [
        po.stem
        for po in catalogues
        if (read_translations(po).get(previous) or "").strip()
    ]
    return Cost(
        previous=previous,
        ratio=difflib.SequenceMatcher(None, source, previous).ratio(),
        translated=len(translated),
        catalogues=len(catalogues),
        languages=translated,
    )


def iter_gettext_literals(path: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError, UnicodeDecodeError:
        return []
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr
            if isinstance(func, ast.Attribute)
            else None
        )
        if name not in GETTEXT_NAMES:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.append((node.lineno, first.value))
    return found


def measure(roots: tuple[Path, ...] = ADDON_ROOTS) -> tuple[list[Unresolved], dict]:
    modules = iter_modules(roots)
    if not modules:
        raise RuntimeError(
            "no module ships an i18n/<module>.pot under "
            + ", ".join(_sources.display(r, ROOT) for r in roots)
            + " -- refusing to report a clean zero on a tree this gate never read"
        )
    unresolved: list[Unresolved] = []
    total = 0
    for module, module_dir, pot in modules:
        msgids = read_msgids(pot)
        for source_file in sorted(module_dir.rglob("*.py")):
            if "__pycache__" in source_file.parts or _sources.is_test_path(source_file):
                continue
            for lineno, text in iter_gettext_literals(source_file):
                total += 1
                if text not in msgids:
                    unresolved.append(
                        Unresolved(module, _sources.display(source_file, ROOT), lineno, text)
                    )
    stats = {"modules": len(modules), "strings": total, "unresolved": len(unresolved)}
    return unresolved, stats


def by_module(found: list[Unresolved]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in found:
        counts[item.module] = counts.get(item.module, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--module", help="report one module in full")
    parser.add_argument(
        "--cost",
        action="store_true",
        help="for each string, what rewording into it would strand (reads the .po files)",
    )
    parser.add_argument("--top", type=int, default=20, help="0 for all")
    parser.add_argument(
        "--check", action="store_true", help="exit non-zero if anything is unresolved"
    )
    doc_measured.main_flags(parser)
    args = parser.parse_args(argv)

    try:
        found, stats = measure()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.check_doc or args.update_doc:
        path = Path(__file__).resolve()
        if args.update_doc:
            changed = doc_measured.update(path, stats)
            print(
                f"[{'upd' if changed else ' ok'}] {doc_measured.render(stats)}",
            )
            return 0
        problems = doc_measured.check(path, stats)
        if problems:
            print("module docstring's MEASURED block is stale:")
            for problem in problems:
                print(f"  {problem}")
            print("\n  python tooling/architecture/translation_catalog.py --update-doc")
            return 1
        print(f"[ ok] MEASURED block is fresh: {doc_measured.render(stats)}")
        return 0

    if args.module:
        found = [item for item in found if item.module == args.module]

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(f) for f in found], indent=2))
        return 0

    print("Translatable strings with no msgid in their module's catalogue")
    print("=" * 72)
    counts = by_module(found)
    if args.module:
        shown = found if args.top == 0 else found[: args.top]
        catalogues = {}
        for item in shown:
            print(item)
            if not args.cost:
                continue
            module_dir = next(
                (d for name, d, _pot in iter_modules() if name == item.module), None
            )
            if module_dir is None:
                continue
            if item.module not in catalogues:
                catalogues[item.module] = read_msgids(
                    module_dir / "i18n" / f"{item.module}.pot"
                )
            cost = reword_cost(item.source, module_dir, catalogues[item.module])
            if cost is None:
                print("           new: nothing near it in the catalogue, costs nothing")
            else:
                print(
                    f"           looks like a rewording of {cost.previous[:56]!r}"
                    f" ({cost.ratio:.2f})"
                )
                verdict = (
                    f"strands {cost.translated} translation(s)"
                    if cost.translated
                    else "strands nothing: that msgid is untranslated everywhere"
                )
                print(
                    f"           {verdict}, of {cost.catalogues} catalogues"
                    + (f": {' '.join(cost.languages[:12])}" if cost.translated else "")
                )
        if len(found) > len(shown):
            print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    else:
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        shown = ranked if args.top == 0 else ranked[: args.top]
        for module, count in shown:
            print(f"  {count:5d}  {module}")
        if len(ranked) > len(shown):
            print(
                f"  ... and {len(ranked) - len(shown)} more modules (--top 0 for all)"
            )
    print("-" * 72)
    print(
        f"\n{stats['unresolved']} of {stats['strings']} strings in "
        f"{stats['modules']} modules cannot be resolved"
    )
    print(
        "\nIf one of these is a string you just wrote, export -- do not move the floor:"
    )
    print("  odoo-bin i18n export -c <conf> -d <db> <module>")
    print("\nThe floor is for debt you are accepting, not for a string you introduced:")
    print("  python tooling/architecture/translation_catalog.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py translations --count")
    return 1 if (args.check and found) else 0


if __name__ == "__main__":
    sys.exit(main())
