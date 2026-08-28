import argparse
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from xml.parsers import expat

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import SIBLING_REPOS, find_odoo_root

ADR = "0032"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="xml_reference_coherence")
ANALYZER = Path(__file__).with_suffix(".mjs")
PINNED = Path(__file__).resolve().parent / "xml_reference_coherence.txt"

SCOPES = (("odoo", ROOT), *((name, ROOT.parent / name) for name in SIBLING_REPOS))

CLOSURES: dict[str, tuple[str, ...]] = {
    "odoo": ("odoo",),
    "enterprise": ("odoo", "enterprise"),
    "design-themes": ("odoo", "enterprise", "design-themes"),
    "agromarin": ("odoo", "enterprise", "design-themes", "agromarin"),
}

VIEW_PREFIXES = frozenset(
    {"list", "form", "kanban", "calendar", "hierarchy", "base_settings"}
)

JS_NEEDLES = (
    "registerField",
    "registerFallbackField",
    'category("fields")',
    'category("views")',
    'category("view_widgets")',
    'category("formatters")',
    'category("grid_components")',
    "category('fields')",
    "category('views')",
    "category('view_widgets')",
    "category('formatters')",
    "category('grid_components')",
)

FORMATTER_ROOTS = frozenset({"pivot", "graph", "cohort"})
GRID_ROOTS = frozenset({"grid"})
FIELDS_ROOTS = frozenset(
    {
        "form",
        "list",
        "tree",
        "kanban",
        "calendar",
        "activity",
        "hierarchy",
        "map",
        "gantt",
        "search",
    }
)

KIND_TO_CATEGORY = {
    "widget": "fields",
    "widget_formatter": "formatters",
    "widget_grid": "grid_components",
    "js_class": "views",
    "view_widget": "view_widgets",
    "t-call": "templates",
    "t-inherit": "templates",
}

_SKIP_PARTS = {"node_modules", "__pycache__", "lib"}


@dataclass(frozen=True)
class Ref:
    kind: str
    name: str
    file: str
    line: int
    scope: str
    in_tests: bool


def _named_roots(scopes) -> list[tuple[str, Path]]:

    named = []
    for item in scopes:
        if isinstance(item, tuple):
            name, root = item[0], Path(item[1])
        else:
            root = Path(item)
            name = root.name
        if root.is_dir():
            named.append((name, root))
    return named


def _addon_dirs(name: str, root: Path) -> list[Path]:

    if name == "odoo":
        dirs = [root / "addons", root / "odoo" / "addons"]
        found = [d for d in dirs if d.is_dir()]
        return found or [root]
    return [root]


def _skippable(path: Path) -> bool:
    return any(p in _SKIP_PARTS or p.startswith(".") for p in path.parts)


def _in_tests(posix: str) -> bool:
    return "/static/tests/" in posix or posix.startswith("static/tests/")


def _js_candidates(named: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
    out = []
    for name, root in named:
        for base in _addon_dirs(name, root):
            for path in sorted(base.rglob("*.js")):
                if _skippable(path.relative_to(base)):
                    continue
                if "/static/" not in path.as_posix():
                    continue
                try:
                    text = path.read_text(encoding="utf8", errors="replace")
                except OSError:  # pragma: no cover
                    continue
                if any(needle in text for needle in JS_NEEDLES):
                    out.append((name, path))
    return out


def _run_analyzer(files: list[Path]) -> list[dict]:
    if not files:
        return []
    proc = subprocess.run(
        ["node", str(ANALYZER), *[str(f) for f in files]],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"reference-coherence analyzer failed: {proc.stderr.strip()}"
        )
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def collect_js_providers(
    named: list[tuple[str, Path]], unverifiable: Counter
) -> dict[str, dict[str, tuple[set[str], set[str]]]]:
    candidates = _js_candidates(named)
    scope_of = {str(path): scope for scope, path in candidates}
    providers: dict[str, dict[str, tuple[set[str], set[str]]]] = {}
    for rec in _run_analyzer([path for _, path in candidates]):
        scope = scope_of[rec["file"]]
        if rec["kind"] == "dynamic":
            unverifiable["dynamic JS registration key"] += 1
            continue
        cat = providers.setdefault(scope, {}).setdefault(
            rec["category"], (set(), set())
        )
        cat[1 if _in_tests(Path(rec["file"]).as_posix()) else 0].add(rec["key"])
    return providers


class _TemplateScan:
    def __init__(self):
        self.names: list[str] = []
        self.refs: list[tuple[str, str, int]] = []
        self.dynamic = 0
        self._parser = None

    def start(self, tag, attrs):
        line = self._parser.CurrentLineNumber
        if "t-name" in attrs:
            self.names.append(attrs["t-name"])
        for attr in ("t-call", "t-inherit"):
            value = attrs.get(attr, "")
            if not value:
                continue
            if "{{" in value or "#{" in value:
                self.dynamic += 1
            else:
                self.refs.append((attr, value, line))

    def parse(self, data: bytes):
        self._parser = expat.ParserCreate()
        self._parser.StartElementHandler = self.start
        self._parser.Parse(data, True)


class _ArchScan:
    def __init__(self):
        self.refs: list[tuple[str, str, int]] = []
        self._stack: list[str] = []
        self._capture: tuple[str, int] | None = None
        self._chunks: list[str] = []
        self._parser = None

    def _widget_kind(self) -> str:
        for tag in reversed(self._stack):
            if tag in FIELDS_ROOTS:
                return "widget"
            if tag in FORMATTER_ROOTS:
                return "widget_formatter"
            if tag in GRID_ROOTS:
                return "widget_grid"
        return "widget_unscoped"

    def start(self, tag, attrs):
        line = self._parser.CurrentLineNumber
        if tag == "field" and attrs.get("widget"):
            self.refs.append((self._widget_kind(), attrs["widget"], line))
        if tag == "widget" and attrs.get("name"):
            self.refs.append(("view_widget", attrs["name"], line))
        if attrs.get("js_class"):
            self.refs.append(("js_class", attrs["js_class"], line))
        if tag == "attribute" and attrs.get("name") in ("widget", "js_class"):
            kind = "widget_unscoped" if attrs["name"] == "widget" else "js_class"
            self._capture = (kind, line)
            self._chunks = []
        self._stack.append(tag)

    def chars(self, data):
        if self._capture is not None:
            self._chunks.append(data)

    def end(self, tag):
        self._stack.pop()
        if tag == "attribute" and self._capture is not None:
            kind, line = self._capture
            value = "".join(self._chunks).strip()
            if value:
                self.refs.append((kind, value, line))
            self._capture = None

    def parse(self, data: bytes):
        self._parser = expat.ParserCreate()
        self._parser.StartElementHandler = self.start
        self._parser.EndElementHandler = self.end
        self._parser.CharacterDataHandler = self.chars
        self._parser.Parse(data, True)


def collect_xml(
    named: list[tuple[str, Path]], unverifiable: Counter
) -> tuple[dict[str, tuple[set[str], set[str]]], list[Ref], int]:

    templates: dict[str, tuple[set[str], set[str]]] = {}
    consumers: list[Ref] = []
    scanned = 0
    for scope, root in named:
        for base in _addon_dirs(scope, root):
            for path in sorted(base.rglob("*.xml")):
                rel = path.relative_to(base)
                if _skippable(rel):
                    continue
                posix = path.as_posix()
                rel_posix = path.relative_to(root).as_posix()
                is_static = "/static/" in posix
                scan = _TemplateScan() if is_static else _ArchScan()
                try:
                    scan.parse(path.read_bytes())
                except expat.ExpatError, OSError:
                    unverifiable["unparsable XML file"] += 1
                    continue
                scanned += 1
                in_tests = _in_tests(posix)
                if is_static:
                    slot = templates.setdefault(scope, (set(), set()))
                    slot[1 if in_tests else 0].update(scan.names)
                    unverifiable["dynamic t-call/t-inherit"] += scan.dynamic
                for kind, value, line in scan.refs:
                    consumers.append(Ref(kind, value, rel_posix, line, scope, in_tests))
    return templates, consumers, scanned


def _universe(
    js_providers, templates, closure: tuple[str, ...], include_tests: bool
) -> dict[str, set[str]]:
    keys: dict[str, set[str]] = {
        "fields": set(),
        "views": set(),
        "view_widgets": set(),
        "formatters": set(),
        "grid_components": set(),
        "templates": set(),
    }
    slots = (0, 1) if include_tests else (0,)
    for scope in closure:
        for category, sets in js_providers.get(scope, {}).items():
            for slot in slots:
                keys[category] |= sets[slot]
        tmpl = templates.get(scope)
        if tmpl:
            for slot in slots:
                keys["templates"] |= tmpl[slot]
    return keys


def _field_base_names(field_keys: set[str]) -> set[str]:
    out = set()
    for key in field_keys:
        prefix, _, rest = key.partition(".")
        if rest and prefix in VIEW_PREFIXES:
            out.add(rest)
    return out


def resolve(
    js_providers, templates, consumers: list[Ref], judged_scopes: list[str]
) -> list[Ref]:
    dangling: list[Ref] = []
    universes: dict[tuple[str, bool], dict[str, set[str]]] = {}
    bases: dict[tuple[str, bool], set[str]] = {}
    for scope in judged_scopes:
        for include_tests in (False, True):
            uni = _universe(
                js_providers, templates, CLOSURES.get(scope, (scope,)), include_tests
            )
            universes[(scope, include_tests)] = uni
            bases[(scope, include_tests)] = _field_base_names(uni["fields"])
    for ref in consumers:
        if ref.scope not in judged_scopes:
            continue
        uni = universes[(ref.scope, ref.in_tests)]
        if ref.kind == "widget_unscoped":
            provided = uni["fields"] | uni["formatters"] | uni["grid_components"]
        else:
            provided = uni[KIND_TO_CATEGORY[ref.kind]]
        if ref.name in provided:
            continue
        if (
            ref.kind in ("widget", "widget_unscoped")
            and ref.name in bases[(ref.scope, ref.in_tests)]
        ):
            continue
        dangling.append(ref)
    return dangling


def load_pinned(path: Path | None = None) -> dict[str, frozenset[str]]:
    path = PINNED if path is None else path
    pinned: dict[str, frozenset[str]] = {}
    if not path.is_file():
        return pinned
    for line in path.read_text(encoding="utf8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entry, *tags = line.split()
        pinned[entry] = frozenset(tags)
    return pinned


def _scope_order(scope: str) -> tuple[int, str]:
    names = [name for name, _ in SCOPES]
    return (names.index(scope) if scope in names else len(names), scope)


def measured_provenance(dangling: list[Ref]) -> dict[str, frozenset[str]]:
    found: dict[str, set[str]] = {}
    for ref in dangling:
        found.setdefault(f"{ref.kind}:{ref.name}", set()).add(ref.scope)
    return {entry: frozenset(scopes) for entry, scopes in found.items()}


def write_pinned(provenance: dict[str, frozenset[str]], path: Path | None = None):
    path = PINNED if path is None else path
    header = (
        "# Dangling XML string references: view-arch / template strings that\n"
        "# no JS registration or t-name in the consumer scope's provider\n"
        "# closure satisfies. Pinned by tooling/architecture/\n"
        "# xml_reference_coherence.py --update; each entry names the consumer\n"
        "# scope(s) it dangles in, and --check judges only the scopes whose\n"
        "# provider closure is present.\n"
        "#\n"
        "# Shrink-only, per scope: a NEW dangling reference fails the gate,\n"
        "# and a pinned one that stopped dangling fails until this list is\n"
        "# shrunk, so the fix is recorded rather than silently re-spendable.\n"
    )
    lines = [
        f"{entry}  {' '.join(sorted(scopes, key=_scope_order))}"
        for entry, scopes in sorted(provenance.items())
    ]
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf8")


def drift(
    provenance: dict[str, frozenset[str]],
    pinned: dict[str, frozenset[str]],
    judged_scopes: list[str],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:

    new: dict[str, list[str]] = {}
    gone: dict[str, list[str]] = {}
    for scope in judged_scopes:
        measured_scope = {e for e, scopes in provenance.items() if scope in scopes}
        pinned_scope = {e for e, tags in pinned.items() if scope in tags}
        grown = sorted(measured_scope - pinned_scope)
        shrunk = sorted(pinned_scope - measured_scope)
        if grown:
            new[scope] = grown
        if shrunk:
            gone[scope] = shrunk
    return new, gone


def judged(present: list[str]) -> list[str]:
    return [s for s in present if all(dep in present for dep in CLOSURES.get(s, (s,)))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on drift")
    parser.add_argument("--update", action="store_true", help="rewrite the pin")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    named = _named_roots(SCOPES)
    present = [name for name, _ in named]
    absent = [name for name, _ in SCOPES if name not in present]

    if args.update and absent:
        parser.error(
            "--update needs every consumer checkout present; missing: "
            + ", ".join(absent)
        )

    unverifiable: Counter = Counter()
    js_providers = collect_js_providers(named, unverifiable)
    templates, consumers, xml_scanned = collect_xml(named, unverifiable)

    if not consumers:
        parser.error("no XML string references found — the scan reached nothing")
    if not js_providers and not templates:
        parser.error("no providers found in any scope — the scan reached nothing")

    judged_scopes = judged(present)
    dangling = resolve(js_providers, templates, consumers, judged_scopes)
    provenance = measured_provenance(dangling)

    if args.update:
        write_pinned(provenance)
        print(f"wrote {PINNED.name}: {len(provenance)} dangling reference(s)")
        return 0

    pinned = load_pinned()
    new, gone = drift(provenance, pinned, judged_scopes)

    if args.json:
        print(
            json.dumps(
                {
                    "scopes_present": present,
                    "scopes_judged": judged_scopes,
                    "consumers": len(consumers),
                    "xml_files": xml_scanned,
                    "dangling": {e: sorted(s) for e, s in sorted(provenance.items())},
                    "unverifiable": dict(unverifiable),
                    "new": new,
                    "gone": gone,
                },
                indent=2,
            )
        )
        return 1 if ((new or gone) and args.check) else 0

    by_kind = Counter(ref.kind for ref in consumers)
    dangling_by_kind = Counter(ref.kind for ref in dangling)
    print("XML string-reference coherence (widget/js_class/view_widget/t-call)")
    print("=" * 68)
    print(f"consumer scopes present: {', '.join(present)}")
    if absent:
        print(f"  absent, skipped: {', '.join(absent)}")
    print(f"  judged (provider closure present): {', '.join(judged_scopes)}")
    print(f"\n{len(consumers)} references in {xml_scanned} XML files:")
    for kind, n in by_kind.most_common():
        d = dangling_by_kind.get(kind, 0)
        print(f"  {n:>6}  {kind:<12} ({d} dangling)")
    if unverifiable:
        print("\nunverifiable (counted, never failed on):")
        for reason, n in unverifiable.most_common():
            print(f"  {n:>6}  {reason}")
    examples: dict[str, Ref] = {}
    for ref in dangling:
        examples.setdefault(f"{ref.kind}:{ref.name}", ref)
    for scope, entries in new.items():
        print(f"\n[FAIL] scope '{scope}': {len(entries)} NEW dangling reference(s):")
        for entry in entries[:20]:
            ref = examples.get(entry)
            where = f"  ({ref.file}:{ref.line})" if ref else ""
            print(f"    {entry}{where}")
        if len(entries) > 20:
            print(f"    … and {len(entries) - 20} more")
    for scope, entries in gone.items():
        print(
            f"\n[FAIL] scope '{scope}': {len(entries)} pinned entr(ies) no longer "
            f"dangling — shrink the pin:"
        )
        for entry in entries[:20]:
            print(f"    {entry}")
        if len(entries) > 20:
            print(f"    … and {len(entries) - 20} more")
    print("-" * 68)
    if not new and not gone:
        print(
            f"\n{len(provenance)} dangling reference(s), all pinned. "
            f"No drift across {len(judged_scopes)} judged scope(s). ✓"
        )

    return 1 if ((new or gone) and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
