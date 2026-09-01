from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_eager_mock_fixture")

IMPORT_BINDING = re.compile(
    r"""\bimport\s+(?P<clause>\{[^}]*\}|\*\s+as\s+[A-Za-z_$][\w$]*|[A-Za-z_$][\w$]*)"""
    r"""\s+from\s*['"](?P<spec>[^'"\n]+)['"]"""
)
RECORDS_MUTATION = re.compile(
    r"^(?P<name>[A-Za-z_$][\w$]*)\._records\s*(?:=[^=]|\.push\b|\.splice\b)",
    re.MULTILINE,
)
PATCH_BINDING = re.compile(
    r"^patch\(\s*(?P<name>[A-Za-z_$][\w$]*)\s*,\s*\[", re.MULTILINE
)


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    binding: str
    shape: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.binding}  ({self.shape})"


def foreign_bindings(text: str, addon: str) -> set[str]:
    bindings: set[str] = set()
    for match in IMPORT_BINDING.finditer(text):
        spec = match.group("spec")
        if not spec.startswith("@"):
            continue
        if spec[1:].partition("/")[0] == addon:
            continue
        clause = match.group("clause")
        if clause.startswith("{"):
            for part in clause.strip("{}").split(","):
                names = re.findall(r"[A-Za-z_$][\w$]*", part)
                if names:
                    bindings.add(names[-1])
        else:
            names = re.findall(r"[A-Za-z_$][\w$]*", clause)
            if names:
                bindings.add(names[-1])
    return bindings


def addon_of(path: Path) -> str | None:
    parts = path.as_posix().split("/static/tests/")
    return parts[0].rsplit("/", 1)[-1] if len(parts) == 2 else None


def measure(roots: list[Path]) -> list[Finding]:
    scanned = 0
    found: list[Finding] = []
    for root in roots:
        for path in sorted(root.glob("*/static/tests/**/*.js")):
            addon = addon_of(path)
            if addon is None:
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            foreign = foreign_bindings(text, addon)
            if not foreign:
                continue
            rel = (
                path.relative_to(ROOT).as_posix()
                if path.is_relative_to(ROOT)
                else path.as_posix()
            )
            for regex, shape in (
                (RECORDS_MUTATION, "_records at module scope"),
                (PATCH_BINDING, "patch() of the imported binding itself"),
            ):
                for match in regex.finditer(text):
                    if match.group("name") not in foreign:
                        continue
                    line = text.count("\n", 0, match.start()) + 1
                    found.append(Finding(rel, line, match.group("name"), shape))
    if not scanned:
        raise RuntimeError("no static/tests JS found under the given roots")
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--top", type=int, default=20, help="offenders to list (0 = all)"
    )
    parser.add_argument(
        "roots",
        nargs="*",
        default=None,
        help="directories to scan (default: this repo's addons/)",
    )
    args = parser.parse_args(argv)

    roots = [Path(r).resolve() for r in args.roots] if args.roots else [ROOT / "addons"]
    try:
        found = measure(roots)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(f) for f in found], indent=2))
        return 0

    print("Mock fixtures mutating another addon's model at module scope")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    print(f"\n{len(found)} eager fixture mutation(s)")
    print("\nRatchet this number:")
    print("  python tooling/architecture/js_eager_mock_fixture.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py jseagerfixture --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())
