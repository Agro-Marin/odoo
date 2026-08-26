import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0044"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_vacuous_assertions")

SCANNED_SUFFIXES = (".js", ".xml", ".scss", ".css")

ZERO_COUNT = re.compile(
    r"""expect\(\s*[`"']([^`"'\n]{3,200})[`"']\s*\)\s*\.toHaveCount\(\s*0\b"""
)
SELECTOR_CLASS = re.compile(r"\.([a-zA-Z_][\w-]*)")
WORD = re.compile(r"[\w-]+")

OWNED_PREFIXES = ("o_", "o-", "oi-", "fa-")

MIN_COMPOSED_SEGMENT = 4


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    css_class: str
    selector: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  .{self.css_class}   in  {self.selector}"


def is_test(path: Path) -> bool:
    return path.name.endswith(".test.js") or "/static/tests/" in path.as_posix()


def collect(roots: list[Path]) -> tuple[set[str], list[tuple[Path, str]]]:
    declared: set[str] = set()
    tests: list[tuple[Path, str]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
                continue
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            if is_test(path):
                if path.name.endswith(".test.js"):
                    tests.append((path, text))
            else:
                declared |= set(WORD.findall(text))
    return declared, tests


def is_composed(css_class: str, declared: set[str]) -> bool:
    for namespace in OWNED_PREFIXES:
        if not css_class.startswith(namespace):
            continue
        for prefix in declared:
            if css_class == prefix or not css_class.startswith(prefix):
                continue
            if prefix[-1] not in "_-":
                continue
            if len(prefix) - len(namespace) >= MIN_COMPOSED_SEGMENT:
                return True
    return False


def measure(roots: list[Path]) -> list[Finding]:
    declared, tests = collect(roots)
    if not tests:
        raise RuntimeError(
            "no *.test.js under "
            + ", ".join(str(r) for r in roots)
            + " -- the scan reached nothing"
        )
    found: list[Finding] = []
    for path, text in tests:
        rel = (
            path.relative_to(ROOT).as_posix()
            if path.is_relative_to(ROOT)
            else str(path)
        )
        matches = list(ZERO_COUNT.finditer(text))
        asserted = "".join(m.group(1) for m in matches)
        for match in matches:
            selector = match.group(1)
            line = text.count("\n", 0, match.start()) + 1
            for css_class in sorted(set(SELECTOR_CLASS.findall(selector))):
                if not css_class.startswith(OWNED_PREFIXES):
                    continue
                if css_class in declared or is_composed(css_class, declared):
                    continue
                if text.count(css_class) > asserted.count(css_class):
                    continue
                found.append(Finding(rel, line, css_class, selector))
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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

    print("Zero-count assertions on a class no markup declares")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    print(f"\n{len(found)} vacuous assertion(s)")
    print("\nRatchet this number:")
    print("  python tooling/architecture/js_vacuous_assertions.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py jsvacuous --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())
