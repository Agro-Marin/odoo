import argparse
import json
import re
import sys
from pathlib import Path

from js_imports import strip_comments

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _consumer_scopes
import doc_measured
from _repo_root import find_odoo_root

ADR = "0020"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_extension_surface")
WEB = ROOT / "addons" / "web"
PINNED = Path(__file__).resolve().parent / "extension_surface_web.txt"

CONSUMER_ROOTS = _consumer_scopes.CONSUMER_ROOTS

REPO_ROOTS = CONSUMER_ROOTS[:1]

NOT_CONTRACT = frozenset(
    {"template", "props", "components", "defaultProps", "constructor"}
)

_IMPORT = re.compile(r'import\s*\{([^}]*)\}\s*from\s*["\']([^"\']+)["\']', re.DOTALL)
_REEXPORT = re.compile(r'export\s*\{([^}]*)\}\s*from\s*["\']([^"\']+)["\']', re.DOTALL)
_STAR = re.compile(r'export\s*\*\s*from\s*["\']([^"\']+)["\']')
_EXTENDS = (
    r"(?:([A-Za-z_$][\w$]*)\s*\(\s*([A-Za-z_$][\w$]*)"
    r"|([A-Za-z_$][\w$]*)(?:\.([A-Za-z_$][\w$]*))?)"
)
_CLASS = re.compile(
    r"^(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)\s*(?:extends\s+"
    + _EXTENDS
    + r")?",
    re.MULTILINE,
)
_METHOD = re.compile(
    r"^\s{4}(?:static\s+)?(?:async\s+)?(?:\*\s*)?(?:get\s+|set\s+)?"
    r"([a-zA-Z_$][\w$]*)\s*[(=]",
    re.MULTILINE,
)
_DESCRIPTOR = re.compile(
    r"(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*\{(.*?)\n\}", re.DOTALL
)
_PATCH = re.compile(r"\bpatch\(\s*([A-Za-z_$][\w$]*)(\.prototype)?\s*,")
_PATCH_MEMBER = re.compile(
    r"(?:async\s+)?(?:\*\s*)?(?:get\s+|set\s+)?([A-Za-z_$][\w$]*)"
)
_DESC_PROP = re.compile(
    r"^\s*([A-Za-z_$][\w$]*)\s*:\s*([A-Za-z_$][\w$]*)\s*,?\s*$", re.MULTILINE
)


def _skip(path: Path) -> bool:

    text = path.as_posix()
    return "/static/lib/" in text or "/node_modules/" in text


def addon_aliases(consumer_roots=CONSUMER_ROOTS) -> dict[str, Path]:

    aliases: dict[str, Path] = {}
    for _name, root in _named_roots(consumer_roots):
        for addons in (root / "addons", root):
            if not addons.is_dir():
                continue
            for entry in addons.iterdir():
                src = entry / "static" / "src"
                if src.is_dir():
                    aliases.setdefault(entry.name, src)
    return aliases


def _named_roots(consumer_roots) -> list[tuple[str, Path]]:
    named = []
    for item in consumer_roots:
        if isinstance(item, tuple):
            name, root = item[0], Path(item[1])
        else:
            root = Path(item)
            name = root.name
        if root.is_dir():
            named.append((name, root))
    return named


def _class_body(src: str, start: int) -> str:
    opening = src.find("{", start)
    if opening < 0:
        return ""
    depth = 0
    for index in range(opening, len(src)):
        if src[index] == "{":
            depth += 1
        elif src[index] == "}":
            depth -= 1
            if depth == 0:
                return src[opening:index]
    return ""


def object_literal_members(src: str, after: int) -> set[str]:

    opening = src.find("{", after)
    if opening < 0:
        return set()
    members: set[str] = set()
    depth = 0
    buf: list[str] = []
    for index in range(opening, len(src)):
        char = src[index]
        if char == "{":
            depth += 1
            buf = []
            continue
        if char == "}":
            depth -= 1
            buf = []
            if depth == 0:
                break
            continue
        if depth != 1:
            continue
        if char in "\n,;":
            buf = []
        elif char in "(:":
            candidate = "".join(buf).strip().lstrip(",").strip()
            match = _PATCH_MEMBER.fullmatch(candidate)
            if match:
                members.add(match.group(1))
            buf = []
        else:
            buf.append(char)
    return members


def scan_file(source: str) -> dict:

    src = strip_comments(source)
    record = {
        "imports": {},
        "reexports": {},
        "stars": _STAR.findall(src),
        "descriptors": {},
        "classes": {},
        "patches": [],
    }
    for names, spec in _IMPORT.findall(src):
        for raw in names.split(","):
            name = raw.strip()
            if not name:
                continue
            parts = [part.strip() for part in name.split(" as ")]
            record["imports"][parts[-1]] = (spec, parts[0])
    for names, spec in _REEXPORT.findall(src):
        for raw in names.split(","):
            name = raw.strip()
            if not name:
                continue
            parts = [part.strip() for part in name.split(" as ")]
            record["reexports"][parts[-1]] = (spec, parts[0])
    for match in _DESCRIPTOR.finditer(src):
        record["descriptors"][match.group(1)] = dict(_DESC_PROP.findall(match.group(2)))
    for match in _CLASS.finditer(src):
        mixin_arg, plain, prop = match.group(3), match.group(4), match.group(5)
        if mixin_arg:
            base, prop, form = mixin_arg, None, "mixin"
        elif plain:
            base, form = plain, "prop" if prop else "plain"
        else:
            base, prop, form = None, None, None
        record["classes"][match.group(1)] = {
            "base": base,
            "prop": prop,
            "form": form,
            "methods": frozenset(_METHOD.findall(_class_body(src, match.end()))),
        }
    for match in _PATCH.finditer(src):
        members = object_literal_members(src, match.end())
        if members:
            record["patches"].append((match.group(1), frozenset(members)))
    return record


class Index:
    def __init__(self, consumer_roots=CONSUMER_ROOTS, web_src=None):
        self.web_src = Path(web_src or WEB / "static" / "src").resolve()
        self.roots = _named_roots(consumer_roots)
        self.aliases = addon_aliases(consumer_roots)
        self.files: dict[Path, dict] = {}
        self.scope_of: dict[Path, str] = {}
        for name, root in self.roots:
            for path in root.rglob("*.js"):
                if _skip(path):
                    continue
                try:
                    source = path.read_text(encoding="utf8")
                except UnicodeDecodeError, OSError:
                    continue
                if len(source) / (source.count("\n") + 1) > 300:
                    continue
                resolved = path.resolve()
                self.files[resolved] = scan_file(source)
                self.scope_of.setdefault(resolved, name)
        self._defs: dict[tuple[Path, str], tuple[Path, str] | None] = {}

    def in_web(self, path: Path) -> bool:
        return path.is_relative_to(self.web_src)

    def is_web_addon(self, path: Path) -> bool:

        return path.is_relative_to(self.web_src.parent.parent)

    def resolve_spec(self, spec: str, origin: Path) -> Path | None:
        if spec.startswith("."):
            base = (origin.parent / spec).resolve()
        else:
            head, _, tail = spec.partition("/")
            alias = self.aliases.get(head.lstrip("@"))
            if alias is None or not tail:
                return None
            base = (alias / tail).resolve()
        for candidate in (base, Path(f"{base}.js"), base / "index.js"):
            if candidate.is_file():
                return candidate.resolve()
        return None

    def find_class(self, path: Path, name: str, depth: int = 0):
        if depth > 12:
            return None
        key = (path, name)
        if key in self._defs:
            return self._defs[key]
        self._defs[key] = None
        record = self.files.get(path)
        if record is None:
            return None
        found = None
        if name in record["classes"]:
            found = (path, name)
        elif name in record["reexports"]:
            spec, original = record["reexports"][name]
            target = self.resolve_spec(spec, path)
            if target:
                found = self.find_class(target, original, depth + 1)
        elif name in record["imports"]:
            spec, original = record["imports"][name]
            target = self.resolve_spec(spec, path)
            if target:
                found = self.find_class(target, original, depth + 1)
        else:
            for spec in record["stars"]:
                target = self.resolve_spec(spec, path)
                if target and (found := self.find_class(target, name, depth + 1)):
                    break
        self._defs[key] = found
        return found

    def find_descriptor(self, path: Path, name: str, depth: int = 0):
        if depth > 10:
            return None
        record = self.files.get(path)
        if record is None:
            return None
        if name in record["descriptors"]:
            return (path, record["descriptors"][name])
        spec = original = None
        if name in record["reexports"]:
            spec, original = record["reexports"][name]
        elif name in record["imports"]:
            spec, original = record["imports"][name]
        if spec:
            target = self.resolve_spec(spec, path)
            if target:
                return self.find_descriptor(target, original, depth + 1)
        for star in record["stars"]:
            target = self.resolve_spec(star, path)
            if target and (found := self.find_descriptor(target, name, depth + 1)):
                return found
        return None

    def parent_of(self, path: Path, name: str):
        info = self.files[path]["classes"].get(name)
        if not info or not info["base"]:
            return None
        if info["form"] == "prop":
            descriptor = self.find_descriptor(path, info["base"])
            if not descriptor:
                return None
            home, properties = descriptor
            target = properties.get(info["prop"])
            return self.find_class(home, target) if target else None
        return self.find_class(path, info["base"])

    def chain(self, path: Path, name: str) -> list[tuple[Path, str]]:
        seen: set[tuple[Path, str]] = set()
        walk: list[tuple[Path, str]] = []
        current = (path, name)
        while current and current not in seen:
            seen.add(current)
            walk.append(current)
            if current[1] not in self.files.get(current[0], {}).get("classes", {}):
                break
            current = self.parent_of(*current)
        return walk


def measure_detailed(
    consumer_roots=CONSUMER_ROOTS, web_src=None
) -> dict[str, dict[str, list[int]]]:

    index = Index(consumer_roots, web_src)
    found: dict[str, dict[str, list[int]]] = {}
    for path, record in index.files.items():
        if index.is_web_addon(path):
            continue
        scope = index.scope_of[path]
        slot = 1 if "/static/tests/" in path.as_posix() else 0
        for name, info in record["classes"].items():
            if not info["base"]:
                continue
            ancestry = [
                (module, cls)
                for module, cls in index.chain(path, name)[1:]
                if index.in_web(module)
            ]
            if not ancestry:
                continue
            for method in info["methods"] - NOT_CONTRACT:
                for module, cls in ancestry:
                    if method in index.files[module]["classes"][cls]["methods"]:
                        found.setdefault(f"{cls}.{method}", {}).setdefault(
                            scope, [0, 0]
                        )[slot] += 1
                        break
        for target, members in record["patches"]:
            defined = index.find_class(path, target)
            if not defined or not index.in_web(defined[0]):
                continue
            ancestry = [
                (module, cls)
                for module, cls in index.chain(*defined)
                if index.in_web(module)
            ]
            for method in members - NOT_CONTRACT:
                for module, cls in ancestry:
                    if method in index.files[module]["classes"][cls]["methods"]:
                        found.setdefault(f"{cls}.{method}", {}).setdefault(
                            scope, [0, 0]
                        )[slot] += 1
                        break
    return found


def overriders(point: str, consumer_roots=CONSUMER_ROOTS, web_src=None) -> list[tuple]:

    owner, _, method = point.rpartition(".")
    index = Index(consumer_roots, web_src)
    found = []
    for path, record in index.files.items():
        if index.is_web_addon(path):
            continue
        for name, info in record["classes"].items():
            if not info["base"] or method not in info["methods"]:
                continue
            for module, cls in index.chain(path, name)[1:]:
                if not index.in_web(module):
                    continue
                if method in index.files[module]["classes"][cls]["methods"]:
                    if cls == owner:
                        found.append((index.scope_of[path], path, name))
                    break
    return sorted(found, key=lambda row: (row[0], str(row[1])))


def provenance(detailed) -> dict[str, frozenset[str]]:
    return {point: frozenset(scopes) for point, scopes in detailed.items()}


def load_pinned() -> dict[str, frozenset[str]]:
    pinned: dict[str, frozenset[str]] = {}
    if not PINNED.is_file():
        return pinned
    for line in PINNED.read_text(encoding="utf8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        point, *tags = line.split()
        pinned[point] = frozenset(tags)
    return pinned


def _scope_order(scope: str) -> tuple[int, str]:
    names = [name for name, _ in CONSUMER_ROOTS]
    return (names.index(scope) if scope in names else len(names), scope)


def write_pinned(measured_provenance: dict[str, frozenset[str]]) -> None:
    header = (
        "# The `Owner.method` points that addons outside `web` reach — by `extends`\n"
        "# or by `patch()`, which depend on the same contract and are merged here:\n"
        "# web's extension surface, as it is rather than as anyone designed it.\n"
        "# Each entry names the consumer checkout(s) reaching it — its provenance —\n"
        "# and the gate judges only the scopes present in the environment.\n"
        "#\n"
        "# Shrink-only, per scope. A point pinned for a scope that no longer\n"
        "# overrides it fails until the entry is shrunk, so giving up surface is\n"
        "# recorded; one overridden from a scope it is not pinned for fails as\n"
        "# new exposure there.\n"
        "#\n"
        "# `js_public_surface.py` pins the MODULES other addons import. This pins\n"
        "# the METHODS they override — a contract the first cannot express, and\n"
        "# which no other gate in this directory models.\n"
        "#\n"
        "# Entries are deliberately unclassified beyond provenance. Many are\n"
        "# reached by exactly one consumer — the worklist for narrowing the\n"
        "# surface, not a judgement this tool may make. No count is restated\n"
        "# here; run the gate, or read its MEASURED block.\n"
        "# Generated by tooling/architecture/js_extension_surface.py --update.\n"
    )
    lines = [
        f"{point}  {' '.join(sorted(scopes, key=_scope_order))}"
        for point, scopes in sorted(measured_provenance.items())
    ]
    PINNED.write_text(header + "\n".join(lines) + "\n", encoding="utf8")


def drift(measured_provenance, pinned, present_scopes):
    new: dict[str, list[str]] = {}
    gone: dict[str, list[str]] = {}
    for scope in present_scopes:
        measured_scope = {
            p for p, scopes in measured_provenance.items() if scope in scopes
        }
        pinned_scope = {p for p, tags in pinned.items() if not tags or scope in tags}
        if grown := sorted(measured_scope - pinned_scope):
            new[scope] = grown
        if shrunk := sorted(pinned_scope - measured_scope):
            gone[scope] = shrunk
    return new, gone


def unresolved(points, web_src=None) -> list[str]:

    declared: dict[str, set[str]] = {}
    src = Path(web_src or WEB / "static" / "src").resolve()
    for path in src.rglob("*.js"):
        if _skip(path):
            continue
        try:
            source = path.read_text(encoding="utf8")
        except UnicodeDecodeError, OSError:
            continue
        for name, info in scan_file(source)["classes"].items():
            declared.setdefault(name, set()).update(info["methods"])
    missing = []
    for point in points:
        owner, _, method = point.rpartition(".")
        if owner not in declared or method not in declared[owner]:
            missing.append(point)
    return sorted(missing)


def metrics(
    detailed=None, consumer_roots=CONSUMER_ROOTS, web_src=None
) -> dict[str, int]:

    if detailed is None:
        detailed = measure_detailed(consumer_roots, web_src)
    totals = {
        point: sum(sum(counts) for counts in scopes.values())
        for point, scopes in detailed.items()
    }
    return {
        "points": len(detailed),
        "sites": sum(totals.values()),
        "single_use": sum(1 for n in totals.values() if n == 1),
        "owners": len({point.rpartition(".")[0] for point in detailed}),
        "subclasses": count_subclasses(consumer_roots, web_src),
        "patch_sites": count_patch_sites(consumer_roots, web_src),
    }


def repo_metrics() -> dict[str, int]:

    return metrics(consumer_roots=REPO_ROOTS)


def count_patch_sites(consumer_roots=CONSUMER_ROOTS, web_src=None) -> int:
    index = Index(consumer_roots, web_src)
    total = 0
    for path, record in index.files.items():
        if index.is_web_addon(path):
            continue
        for target, _members in record["patches"]:
            defined = index.find_class(path, target)
            if defined and index.in_web(defined[0]):
                total += 1
    return total


def count_subclasses(consumer_roots=CONSUMER_ROOTS, web_src=None) -> int:
    index = Index(consumer_roots, web_src)
    total = 0
    for path, record in index.files.items():
        if index.in_web(path):
            continue
        for name, info in record["classes"].items():
            if info["base"] and any(
                index.in_web(module) for module, _ in index.chain(path, name)[1:]
            ):
                total += 1
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on drift")
    parser.add_argument("--update", action="store_true", help="rewrite the pin")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--explain",
        metavar="Owner.method",
        help="list the files overriding one point — the narrowing worklist",
    )
    doc_measured.main_flags(parser)
    args = parser.parse_args(argv)

    if not (WEB / "static" / "src").is_dir():
        parser.error(f"no web addon at {WEB}")

    if args.explain:
        rows = overriders(args.explain)
        if not rows:
            print(f"no subclass overrides {args.explain}")
            return 1
        print(f"{args.explain} — {len(rows)} overrider(s)")
        for scope, path, subclass in rows:
            try:
                shown = path.relative_to(ROOT.parent)
            except ValueError:
                shown = path
            print(f"  [{scope}] {subclass}  {shown}")
        return 0

    present = [name for name, _ in _named_roots(CONSUMER_ROOTS)]
    absent = [name for name, _ in CONSUMER_ROOTS if name not in present]
    if args.update and absent:
        parser.error(
            "--update needs every consumer checkout present; missing: "
            + ", ".join(absent)
        )

    detailed = measure_detailed(CONSUMER_ROOTS)
    if not detailed:
        parser.error("measured an empty surface — the scan reached nothing")
    measured_provenance = provenance(detailed)

    here = Path(__file__).resolve()
    if args.update_doc:
        changed = doc_measured.update(here, repo_metrics())
        print(f"{'rewrote' if changed else 'already fresh:'} MEASURED block")
        return 0
    if args.check_doc:
        problems = doc_measured.check(here, repo_metrics())
        for problem in problems:
            print(f"[FAIL] {problem}")
        if problems:
            print(
                "\n  python tooling/architecture/js_extension_surface.py --update-doc"
            )
        return 1 if problems else 0

    if args.update:
        write_pinned(measured_provenance)
        print(f"wrote {PINNED.name}: {len(measured_provenance)} point(s)")
        return 0

    pinned = load_pinned()
    new, gone = drift(measured_provenance, pinned, present)
    orphaned = unresolved(pinned)

    totals = {
        point: sum(sum(counts) for counts in scopes.values())
        for point, scopes in detailed.items()
    }
    single_use = sorted(p for p, n in totals.items() if n == 1)

    if args.json:
        print(
            json.dumps(
                {
                    "scopes_present": present,
                    "scopes_absent": absent,
                    "measured": len(detailed),
                    "subclass_sites": sum(totals.values()),
                    "single_use": single_use,
                    "new": new,
                    "gone": gone,
                    "orphaned": orphaned,
                },
                indent=2,
            )
        )
        return 1 if ((new or gone or orphaned) and args.check) else 0

    print("JS extension-surface ratchet (shrink-only, per consumer scope)")
    print("=" * 64)
    print(f"consumer scopes present: {', '.join(present)}")
    if absent:
        print(_consumer_scopes.absent_scopes_line("js_extension_surface", absent))
    print(
        f"measured {len(detailed)} override point(s) over {sum(totals.values())} site(s)"
    )
    print(f"  {len(single_use)} reached by exactly one subclass")
    for scope, points in new.items():
        print(f"\n[FAIL] scope '{scope}': {len(points)} NEW override point(s):")
        for point in points[:20]:
            print(f"    {point}  ({totals[point]} subclass(es))")
        if len(points) > 20:
            print(f"    … and {len(points) - 20} more")
    for scope, points in gone.items():
        print(
            f"\n[FAIL] scope '{scope}': {len(points)} pinned point(s) no longer "
            f"overridden from it — shrink the list:"
        )
        for point in points[:20]:
            print(f"    {point}")
        if len(points) > 20:
            print(f"    … and {len(points) - 20} more")
    if orphaned:
        print(
            f"\n[FAIL] {len(orphaned)} pinned point(s) name a method the owning "
            f"class no longer declares:"
        )
        for point in orphaned:
            print(f"    {point}")
        print("    A rename inside web orphaned these. Update the pin with the rename.")
    print("-" * 64)
    if not new and not gone and not orphaned:
        print(f"\nExtension surface unchanged across {len(present)} scope(s). ✓")

    return 1 if ((new or gone or orphaned) and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
