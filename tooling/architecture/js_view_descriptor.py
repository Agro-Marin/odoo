"""Every base view type's parser extends ViewArchParser, and a model asked for sample data can answer hasData().

Two halves of the view-type contribution contract that nothing held:

The parser. `ViewArchParser` is the base web ships for arch parsing, and for
a year zero of nine extension parsers extended it -- `web_map`'s said why in
a comment: the base was on no public-surface row, so the first import would
have failed a shrink-only pin. The row exists now and eight of nine extend it;
this gate is what keeps the ninth from coming back.

Sample data. `useModelWithSampleData` swaps in a sample ORM only when
`model.hasData()` answers false, and `Model.hasData()` answers true
unconditionally. A controller that asks for sample data with a model that
never overrides it has sample mode that can never activate -- `<view
sample="1">` is inert and the template's `useSampleModel` read is dead. The
hook warns at runtime, in the console, once, per mount; this gate says it
once, per tree, before the code runs.

Both are resolved through the class chain across every scanned repository,
so a parser extending `KanbanArchParser`, or a model extending
`RelationalModel`, passes on its ancestor. A view type this gate cannot
resolve is REPORTED, never skipped.

The Studio editor. web_studio depended on the view modules whose editors it
shipped, so a type was editable in Studio only by a pull request against
web_studio, and five never got one. Since the inversion a view type
contributes its own `studio_editors` entry, from a `<module>_studio` bridge
or from web_studio's own editors/ for the types web ships. A base type with
no entry anywhere is pinned in STUDIO_EDITOR_PINNED with a reason, and that
pin is shrink-only: a type that gains an editor leaves it in the same commit.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from js_view_chassis import SCAN_ROOTS, _module_of, base_view_types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PARSER_BASE = "ViewArchParser"
SAMPLE_HOOK = "useModelWithSampleData"
# Controllers that call the sample hook on behalf of their subclasses.
SAMPLE_CONTROLLER_BASES = ("ReportController", "MultiRecordController")
MAX_CHAIN = 12
STUDIO_EDITORS = re.compile(
    r"""registry\s*\.\s*category\(\s*["']studio_editors["']\s*\)\s*\.\s*add\(\s*["'](?P<key>[^"']+)["']"""
)
# Base view types with no Studio editor, each with why. Shrink-only.
STUDIO_EDITOR_PINNED: dict[str, str] = {
    "hierarchy": "not yet contributed: web_hierarchy ships no editor",
    "geoengine": "not yet contributed: an agromarin type, and web_studio is enterprise",
    "threed": "not yet contributed: an agromarin type, and web_studio is enterprise",
}
# Bases the tree does not declare: the chain ends there, resolved.
EXTERNAL_BASES = frozenset({"Component"})
# web's Model defines hasData() as the unconditional true this gate is about;
# its definition is the default, not an override.
BASE_MODEL = "Model"
EXTERNAL = Path("<external>")

_FILES: dict[Path, list[tuple[Path, str]]] = {}


def _sources(module: Path) -> list[tuple[Path, str]]:
    roots = (module, *(r for r in SCAN_ROOTS if r.is_dir()))
    out: list[tuple[Path, str]] = []
    for root in roots:
        if root in _FILES:
            out.extend(_FILES[root])
            continue
        found: list[tuple[Path, str]] = []
        for js in root.rglob("*.js"):
            text = str(js)
            if "node_modules" in text or "/static/tests/" in text:
                continue
            try:
                found.append((js, js.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
        _FILES[root] = found
        out.extend(found)
    return out


def find_class(name: str, module: Path) -> tuple[Path, str | None, str] | None:
    """(file, base class name or None, source) for `class <name>`; None if unresolved."""
    pattern = re.compile(
        rf"\bclass\s+{re.escape(name)}\b(?:\s+extends\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?))?"
    )
    for js, src in _sources(module):
        m = pattern.search(src)
        if m:
            return js, m.group(1), src
    return None


def chain(name: str, module: Path) -> list[tuple[str, Path | None, str]]:
    """The class chain from `name` up, as (class, file, source); stops at an unresolved base."""
    out: list[tuple[str, Path | None, str]] = []
    current: str | None = name
    for _ in range(MAX_CHAIN):
        if not current:
            break
        if current in EXTERNAL_BASES:
            out.append((current, EXTERNAL, ""))
            break
        hit = find_class(current.split(".")[-1], module)
        if hit is None:
            out.append((current, None, ""))
            break
        js, base, src = hit
        out.append((current, js, src))
        current = base
    return out


def _method_defined(src: str, method: str) -> bool:
    # A definition is followed by a body; a call (`this.hasData()`) is not.
    return (
        re.search(rf"(?<![\w$.])(?:async\s+)?{method}\s*\([^)]*\)\s*\{{", src)
        is not None
    )


def studio_editor_types(scan_roots=None) -> set[str]:
    """Every key any file registers in `studio_editors`."""
    scan_roots = SCAN_ROOTS if scan_roots is None else scan_roots
    keys: set[str] = set()
    for root in scan_roots:
        if not root.is_dir():
            continue
        for js in root.rglob("*.js"):
            text = str(js)
            if "node_modules" in text or "/static/tests/" in text:
                continue
            try:
                src = js.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "studio_editors" not in src:
                continue
            keys.update(m.group("key") for m in STUDIO_EDITORS.finditer(src))
    return keys


def audit(scan_roots=None):
    types = base_view_types(scan_roots)
    parser_bad: list[str] = []
    sample_bad: list[str] = []
    unresolved: list[str] = []
    studio_bad: list[str] = []
    editors = studio_editor_types(scan_roots)
    for view_type in sorted(types):
        if view_type in editors:
            if view_type in STUDIO_EDITOR_PINNED:
                studio_bad.append(
                    f"{view_type}: has a Studio editor now; drop it from STUDIO_EDITOR_PINNED"
                )
        elif view_type not in STUDIO_EDITOR_PINNED:
            studio_bad.append(
                f"{view_type}: no studio_editors entry anywhere, and not pinned with a reason"
            )
    for view_type, (path, literal) in sorted(types.items()):
        module = _module_of(path)
        if module is None:
            unresolved.append(f"{view_type}: {path} is in no addon")
            continue
        parser = re.search(r"\bArchParser\s*:\s*([A-Za-z_$][\w$]*)", literal)
        if parser:
            links = chain(parser.group(1), module)
            names = [c for c, _, _ in links]
            if PARSER_BASE not in names:
                if links[-1][1] is None and links[-1][0] != parser.group(1):
                    unresolved.append(
                        f"{view_type}: parser chain reaches {links[-1][0]}, which resolves nowhere"
                    )
                else:
                    parser_bad.append(
                        f"{view_type}: {parser.group(1)} extends {' -> '.join(names[1:]) or 'nothing'}"
                    )
        controller = re.search(r"\bController\s*:\s*([A-Za-z_$][\w$]*)", literal)
        model = re.search(r"\bModel\s*:\s*([A-Za-z_$][\w$]*)", literal)
        if not controller:
            unresolved.append(f"{view_type}: descriptor names no Controller")
            continue
        clinks = chain(controller.group(1), module)
        if clinks[-1][1] is None:
            unresolved.append(
                f"{view_type}: controller chain reaches {clinks[-1][0]}, which resolves nowhere"
            )
            continue
        asks_sample = any(SAMPLE_HOOK in src for _, _, src in clinks) or any(
            c in SAMPLE_CONTROLLER_BASES for c, _, _ in clinks
        )
        if not asks_sample:
            continue
        if not model:
            sample_bad.append(
                f"{view_type}: asks for sample data with no Model in its descriptor"
            )
            continue
        mlinks = chain(model.group(1), module)
        if mlinks[-1][1] is None and len(mlinks) == 1:
            unresolved.append(f"{view_type}: model {model.group(1)} resolves nowhere")
            continue
        if not any(
            _method_defined(src, "hasData") for c, _, src in mlinks if c != BASE_MODEL
        ):
            sample_bad.append(
                f"{view_type}: {controller.group(1)} asks for sample data and "
                f"{model.group(1)} never overrides hasData(), so it never activates"
            )
    return types, parser_bad, sample_bad, unresolved, studio_bad


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="exit 1 on any finding")
    args = parser.parse_args(argv)

    types, parser_bad, sample_bad, unresolved, studio_bad = audit()
    if not types:
        print(
            "error: no view types found; refusing to report a clean tree",
            file=sys.stderr,
        )
        return 2
    print(f"base view types: {len(types)}")
    print(f"  parser not on {PARSER_BASE}: {len(parser_bad)}")
    for line in parser_bad:
        print(f"      {line}")
    print(f"  sample data asked, hasData() missing: {len(sample_bad)}")
    for line in sample_bad:
        print(f"      {line}")
    print(f"  no Studio editor and not pinned: {len(studio_bad)}")
    for line in studio_bad:
        print(f"      {line}")
    if unresolved:
        print(f"  unresolved: {len(unresolved)}")
        for line in unresolved:
            print(f"      {line}")
    if not args.check:
        return 0
    failures = parser_bad + sample_bad + studio_bad + unresolved
    for f in failures:
        print(f"[FAIL] {f}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
