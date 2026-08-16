import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0025"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_function_length")
WEB_SRC = ROOT / "addons" / "web" / "static" / "src"

GOVERNED_ADDONS = ("web", "mail")
DEFAULT_ADDON = "web"


def addon_src(addon: str = DEFAULT_ADDON):
    return (
        WEB_SRC
        if addon == DEFAULT_ADDON
        else ROOT / "addons" / addon / "static" / "src"
    )


ESLINT = ROOT / "node_modules" / ".bin" / "eslint"

MAX_LINES = 80

GENERATED = frozenset({"emoji_data.js"})

RULE = "max-lines-per-function"
RULE_CONFIG = {
    RULE: [
        "warn",
        {
            "max": MAX_LINES,
            "skipBlankLines": False,
            "skipComments": False,
            "IIFEs": True,
        },
    ]
}

_LINES_RE = re.compile(r"has too many lines \((\d+)\)")


@dataclass(frozen=True)
class LongFunction:
    file: str
    line: int
    lines: int
    what: str

    def __str__(self) -> str:
        return f"  {self.lines:5d}  {self.file}:{self.line}  {self.what}"


def _describe(message: str) -> str:
    return message.split(" has too many lines", maxsplit=1)[0]


_MIXIN_FACTORY_RE = re.compile(r"=>\s*class\s+extends\b")


def _relabel_mixin_factories(found: list[LongFunction], root: Path) -> None:

    cache: dict[str, list[str]] = {}
    for i, item in enumerate(found):
        if not item.what.startswith("Arrow function"):
            continue
        lines = cache.get(item.file)
        if lines is None:
            path = root / item.file
            if not path.is_file():
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            cache[item.file] = lines
        window = " ".join(lines[item.line - 1 : item.line + 1])
        if _MIXIN_FACTORY_RE.search(window):
            found[i] = replace(item, what="Mixin class body")


def measure(src: Path = WEB_SRC, eslint: Path = ESLINT) -> list[LongFunction]:

    if not eslint.is_file():
        raise RuntimeError(f"eslint not found at {eslint} (run `npm ci`)")
    proc = subprocess.run(
        [
            str(eslint),
            ".",
            "--no-config-lookup",
            "--rule",
            json.dumps(RULE_CONFIG),
            "-f",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=src,
    )
    if not proc.stdout.strip():
        raise RuntimeError(
            f"eslint produced no output (exit {proc.returncode}): {proc.stderr[:400]}"
        )
    results = json.loads(proc.stdout)
    if not results:
        raise RuntimeError(f"eslint linted no files under {src}")

    found: list[LongFunction] = []
    for entry in results:
        path = Path(entry["filePath"])
        if path.name in GENERATED:
            continue
        for msg in entry["messages"]:
            if msg.get("ruleId") != RULE:
                continue
            match = _LINES_RE.search(msg["message"])
            if match is None:  # pragma: no cover - rule message format changed
                raise RuntimeError(f"unparsable {RULE} message: {msg['message']!r}")
            found.append(
                LongFunction(
                    file=path.relative_to(ROOT).as_posix()
                    if path.is_relative_to(ROOT)
                    else path.as_posix(),
                    line=msg["line"],
                    lines=int(match.group(1)),
                    what=_describe(msg["message"]),
                )
            )
    found.sort(key=lambda f: (-f.lines, f.file))
    _relabel_mixin_factories(found, ROOT)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--top", type=int, default=15, help="offenders to list (0 = all)"
    )
    parser.add_argument(
        "--addon",
        default=DEFAULT_ADDON,
        choices=GOVERNED_ADDONS,
        help="which addon's static/src to measure (default: web)",
    )
    args = parser.parse_args(argv)

    try:
        found = measure(src=addon_src(args.addon))
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(f) for f in found], indent=2))
        return 0

    print(f"JS function-length budget (> {MAX_LINES} lines, {args.addon}/static/src)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    over = {t: sum(1 for f in found if f.lines > t) for t in (150, 250, 400)}
    print(f"\n{len(found)} function(s) over {MAX_LINES} lines")
    print(f"  over 150: {over[150]}   over 250: {over[250]}   over 400: {over[400]}")
    print("\nRatchet this number:")
    suffix = "" if args.addon == DEFAULT_ADDON else f" --addon {args.addon}"
    name = "jsfunclen" if args.addon == DEFAULT_ADDON else f"jsfunclen_{args.addon}"
    print(f"  python tooling/architecture/js_function_length.py{suffix} --count \\")
    print(f"      | xargs python tooling/ratchet/ratchet.py {name} --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())
