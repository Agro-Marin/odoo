#!/usr/bin/env python3
"""Client source files that opt out of type checking, as a ratchet.

`tsconfig.json` sets `allowJs` with `strict: false` and `noImplicitAny: false`,
and the tree holds eighty `.ts` files of which seventy-nine are `.d.ts` — so the
project config decides almost nothing about how much of this codebase is
actually typed. What decides it is the per-file `// @ts-check` directive: a file
carrying it is compiled with its JSDoc types enforced, and a file without it is
parsed and then believed. The directive is therefore the real adoption boundary,
it is invisible to `tsc`'s own error count (a file that opts out reports zero
errors, exactly like a clean one), and nothing measured it.

The unit is FILES, not errors, and the direction is the count of files WITHOUT
the directive: adding a directive to a file is the move that lowers this gate,
and it is the move that puts the file inside every other type gate at once.
`web` reached 819 of its 821 `static/src` files by hand and no gate held that
ground, so a new file, or a file moved in from another addon, silently gave it
back.

Scope is `static/src` only — `static/tests` and `static/lib` are out. Vendored
code under `static/lib` is not ours to annotate, and the ignore list is read
from `eslint.config.mjs` rather than restated here, so the one place that
already decides which client files are ours decides it for this gate too.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root, sibling_repos_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_ts_check")

SOURCE_SUFFIXES = (".js", ".mjs")

SOURCE_PARTS = ("static", "src")

DIRECTIVE = "@ts-check"

ESLINT_CONFIG = "eslint.config.mjs"

SHARED_IGNORES = "SHARED_IGNORES"

GOVERNED_ADDONS = ("web", "mail", "stock", "account", "point_of_sale")

SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules"})


@dataclass(frozen=True, order=True)
class Unchecked:
    path: str

    def __str__(self) -> str:
        return f"  {self.path}"


def _balanced(source: str, start: int) -> str:
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "[":
            depth += 1
        elif source[index] == "]":
            depth -= 1
            if not depth:
                return source[start : index + 1]
    raise RuntimeError(f"unbalanced array literal at offset {start} in {ESLINT_CONFIG}")


def _strings(block: str) -> list[str]:
    kept = [line for line in block.splitlines() if not line.strip().startswith("//")]
    return re.findall(r'"((?:[^"\\]|\\.)*)"', "\n".join(kept))


def _named_array(source: str, name: str) -> str | None:
    match = re.search(
        rf"^(?:export )?const {re.escape(name)} = \[", source, re.MULTILINE
    )
    return _balanced(source, match.end() - 1) if match else None


def _default_export_ignores(source: str) -> str:
    match = re.search(r"export default makeConfig\(\{", source)
    if match is None:
        raise RuntimeError(
            f"{ESLINT_CONFIG} no longer ends in `export default makeConfig({{`; "
            f"this gate reads its ignore list from there rather than keeping a "
            f"second copy, and it cannot guess"
        )
    field = re.compile(r"\bignores:\s*(\[|\w+)").search(source, match.end())
    if field is None:
        raise RuntimeError(f"{ESLINT_CONFIG} passes no `ignores:` to makeConfig")
    return field.group(1)


def eslint_ignores(repo: Path) -> list[str]:
    odoo_config = ROOT / ESLINT_CONFIG
    if not odoo_config.is_file():
        raise RuntimeError(f"no {odoo_config} — the ignore list has no source")
    odoo_source = odoo_config.read_text(encoding="utf-8")
    shared = _named_array(odoo_source, SHARED_IGNORES)
    if shared is None:
        raise RuntimeError(f"{SHARED_IGNORES} is gone from {ESLINT_CONFIG}")
    patterns = _strings(shared)

    config = repo / ESLINT_CONFIG
    if not config.is_file():
        return patterns
    source = config.read_text(encoding="utf-8")
    field = _default_export_ignores(source)
    if field == "[":
        block = _balanced(source, source.index("[", source.index("ignores:")))
    else:
        block = _named_array(source, field) or _named_array(odoo_source, field)
        if block is None:
            raise RuntimeError(
                f"{config} passes `ignores: {field}` and neither it nor "
                f"{odoo_config} declares that array"
            )
    return patterns + _strings(block)


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    out = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
            continue
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
            continue
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        index += 1
    out.append("$")
    return re.compile("".join(out))


class IgnoreSet:
    def __init__(self, patterns: list[str]) -> None:
        self.rules = [
            (raw.startswith("!"), glob_to_regex(raw.removeprefix("!")))
            for raw in patterns
        ]

    def ignores(self, relative: str) -> bool:
        verdict = False
        for negated, rule in self.rules:
            if rule.match(relative) or rule.match(f"{relative}/"):
                verdict = not negated
        return verdict


def leading_comment(text: str) -> str:
    kept: list[str] = []
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if in_block:
            kept.append(stripped)
            closed = stripped.find("*/")
            if closed >= 0:
                in_block = False
                if stripped[closed + 2 :].strip():
                    break
            continue
        if not stripped:
            continue
        if stripped.startswith("//"):
            kept.append(stripped)
            continue
        if stripped.startswith("/*"):
            kept.append(stripped)
            closed = stripped.find("*/", 2)
            if closed < 0:
                in_block = True
            elif stripped[closed + 2 :].strip():
                break
            continue
        break
    return "\n".join(kept)


def is_checked(text: str) -> bool:
    return DIRECTIVE in leading_comment(text)


def repo_of(root: Path) -> Path:
    workspace = sibling_repos_root(ROOT)
    for candidate in (root, *root.parents):
        if candidate == workspace:
            break
        if (candidate / ESLINT_CONFIG).is_file():
            return candidate
    return root


def iter_source_files(root: Path, addon: str | None = None) -> list[Path]:
    base = root if addon is None else root / addon
    if not base.is_dir():
        return []
    found = [
        path
        for path in base.rglob("*")
        if path.suffix in SOURCE_SUFFIXES
        and not SKIP_DIRS & set(path.parts)
        and _under_static_src(path)
    ]
    return sorted(found)


def _under_static_src(path: Path) -> bool:
    parts = path.parts
    return any(
        parts[index : index + 2] == SOURCE_PARTS for index in range(len(parts) - 1)
    )


def measure(roots: list[Path], addon: str | None = None) -> list[Unchecked]:
    files = [(root, path) for root in roots for path in iter_source_files(root, addon)]
    if not files:
        where = ", ".join(str(root) for root in roots)
        raise RuntimeError(
            f"no {' or '.join(SOURCE_SUFFIXES)} under a static/src of {where} -- "
            f"the scan reached nothing, which is not the same as finding "
            f"every file already checked"
        )
    ignores = {root: IgnoreSet(eslint_ignores(repo_of(root))) for root in roots}
    found: list[Unchecked] = []
    for root, path in files:
        repo = repo_of(root)
        relative = (
            path.relative_to(repo).as_posix()
            if path.is_relative_to(repo)
            else path.as_posix()
        )
        if ignores[root].ignores(relative):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        if not is_checked(text):
            found.append(Unchecked(relative))
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("count static/src client files carrying no leading // @ts-check")
    )
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=25, help="0 for all")
    parser.add_argument(
        "--addon",
        default=None,
        help=(
            "narrow every root to one module: "
            + ", ".join(GOVERNED_ADDONS)
            + ". Onboarding another is a row in GOVERNED_ADDONS and its own "
            "baseline, not a flag"
        ),
    )
    parser.add_argument(
        "roots",
        nargs="*",
        help="directories to scan (default: this repo's addons/)",
    )
    args = parser.parse_args(argv)

    if args.addon is not None and args.addon not in GOVERNED_ADDONS:
        print(
            f"error: {args.addon!r} is not a governed scope. Onboarding one is a "
            f"row in GOVERNED_ADDONS and its own baseline, not a flag: a floor "
            f"over an unscanned tree checks nothing.\n"
            f"       governed: {', '.join(GOVERNED_ADDONS)}",
            file=sys.stderr,
        )
        return 2

    roots = [Path(r).resolve() for r in args.roots] if args.roots else [ROOT / "addons"]
    try:
        found = measure(roots, args.addon)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(item) for item in found], indent=2))
        return 0

    where = args.addon or ", ".join(root.name for root in roots)
    print(f"Client files opting out of type checking ({where})")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    print(f"\n{len(found)} unchecked file(s)   <- the ratcheted number")
    print("\nRatchet it:")
    suffix = f" --addon {args.addon}" if args.addon else ""
    gate = f"jstscheck_{args.addon}" if args.addon else "jstscheck"
    print(f"  python tooling/architecture/js_ts_check.py --count{suffix} \\")
    print(f"      | xargs python tooling/ratchet/ratchet.py {gate} --count")
    return 1 if (found and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
