import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0023"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_suite_parity")
WEB_STATIC = ROOT / "addons" / "web" / "static"

EXEMPT_TEST_DIRS = frozenset({"_framework", "helpers", "mock_server", "tours"})

EXEMPT_SRC_DIRS = frozenset({"scss", "@types"})

KNOWN_UNCOVERED_LAYERS = frozenset({"boot"})

KNOWN_ORPHAN_TEST_DIRS = frozenset(
    {
        "interactions",
        "l10n",
        "modules",
        "ui/notifications",
        "webclient/barcode",
        "webclient/mobile",
    }
)


@dataclass(frozen=True)
class Finding:
    contract: str
    path: str
    detail: str

    def __str__(self) -> str:
        return f"  {self.path:38s} {self.detail}"


def _src_layers(web_static: Path) -> dict[str, int]:
    src = web_static / "src"
    return {
        d.name: len(list(d.rglob("*.js")))
        for d in sorted(src.iterdir())
        if d.is_dir() and d.name not in EXEMPT_SRC_DIRS
    }


def _test_dirs_with_suites(web_static: Path) -> list[str]:
    tests = web_static / "tests"
    found = []
    for d in sorted(p for p in tests.rglob("*") if p.is_dir()):
        rel = d.relative_to(tests).as_posix()
        if rel.split("/")[0] in EXEMPT_TEST_DIRS:
            continue
        if any(d.glob("*.test.js")):
            found.append(rel)
    return found


_REGISTRATION_RE = re.compile(
    r"""register(?:Fallback)?Field\(\s*["']([^"']+)["']"""
    r"""|category\(\s*["'][^"']+["']\s*\)\s*\.\s*add\(\s*["']([^"']+)["']""",
    re.VERBOSE,
)


def _registered_names(js_file: Path) -> set[str]:
    text = js_file.read_text(encoding="utf-8", errors="replace")
    return {m.group(1) or m.group(2) for m in _REGISTRATION_RE.finditer(text)}


def registered_name_hints(web_static: Path, directories: list[str]) -> dict[str, str]:

    src, tests = web_static / "src", web_static / "tests"
    published = {d: set() for d in directories}
    for d in directories:
        for f in (src / d).glob("*.js"):
            published[d] |= _registered_names(f)
    if not any(published.values()):
        return {}
    corpus = "\n".join(
        f.read_text(encoding="utf-8", errors="replace")
        for f in tests.rglob("*")
        if f.is_file() and f.suffix in (".js", ".xml")
    )
    hints = {}
    for d, names in published.items():
        hit = sorted(n for n in names if f'"{n}"' in corpus or f"'{n}'" in corpus)
        if hit:
            hints[d] = hit[0] if len(hit) == 1 else f"{hit[0]} (+{len(hit) - 1})"
    return hints


def uncovered_directories(web_static: Path) -> list[tuple[str, int, int]]:

    src, tests = web_static / "src", web_static / "tests"
    found = []
    for d in sorted(p for p in src.rglob("*") if p.is_dir()):
        rel = d.relative_to(src).as_posix()
        if rel.split("/", maxsplit=1)[0] in EXEMPT_SRC_DIRS:
            continue
        js = sorted(d.glob("*.js"))
        if not js:
            continue
        mirrored = tests / rel
        if mirrored.is_dir() and any(mirrored.glob("*.test.js")):
            continue
        if (tests / f"{rel}.test.js").is_file():
            continue
        parent = mirrored.parent
        if any(
            (mirrored / f"{f.stem}.test.js").is_file()
            or (parent / f"{f.stem}.test.js").is_file()
            for f in js
        ):
            continue
        lines = sum(
            len(f.read_text(encoding="utf-8", errors="replace").splitlines())
            for f in js
        )
        found.append((rel, len(js), lines))
    return found


def find_drift(
    web_static: Path,
    known_uncovered: frozenset[str] | None = None,
    known_orphans: frozenset[str] | None = None,
) -> tuple[list[Finding], list[Finding]]:

    known_uncovered = (
        KNOWN_UNCOVERED_LAYERS if known_uncovered is None else known_uncovered
    )
    known_orphans = KNOWN_ORPHAN_TEST_DIRS if known_orphans is None else known_orphans
    src, tests_root = web_static / "src", web_static / "tests"
    new: list[Finding] = []
    seen_uncovered: set[str] = set()
    seen_orphans: set[str] = set()

    for layer, js_count in _src_layers(web_static).items():
        if js_count == 0:
            continue
        if any((tests_root / layer).rglob("*.test.js")):
            continue
        seen_uncovered.add(layer)
        if layer not in known_uncovered:
            new.append(
                Finding(
                    "layer-coverage",
                    f"src/{layer}/",
                    f"{js_count} JS file(s), but @web/{layer} resolves to 0 suites",
                )
            )

    for rel in _test_dirs_with_suites(web_static):
        if (src / rel).is_dir():
            continue
        seen_orphans.add(rel)
        if rel not in known_orphans:
            count = len(list((tests_root / rel).glob("*.test.js")))
            new.append(
                Finding(
                    "orphan-test-dir",
                    f"tests/{rel}/",
                    f"{count} suite(s), but src/{rel}/ does not exist",
                )
            )

    stale = [
        Finding(
            "stale-known",
            f"src/{layer}/",
            "now covered — remove from KNOWN_UNCOVERED_LAYERS",
        )
        for layer in sorted(known_uncovered - seen_uncovered)
    ] + [
        Finding(
            "stale-known",
            f"tests/{rel}/",
            "now mirrored — remove from KNOWN_ORPHAN_TEST_DIRS",
        )
        for rel in sorted(known_orphans - seen_orphans)
    ]
    return new, stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument(
        "--per-directory",
        action="store_true",
        help="report directories no suite addresses (below contract A's resolution)",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--web-static",
        type=Path,
        default=WEB_STATIC,
        help="path to addons/web/static (defaults to this checkout's)",
    )
    args = parser.parse_args(argv)

    if not (args.web_static / "src").is_dir():
        parser.error(f"no web static tree at {args.web_static}")

    foreign = args.web_static.resolve() != WEB_STATIC.resolve()
    pins = (frozenset(), frozenset()) if foreign else (None, None)

    if args.per_directory:
        uncovered = uncovered_directories(args.web_static)
        total = sum(
            1
            for d in args.web_static.joinpath("src").rglob("*")
            if d.is_dir()
            and any(d.glob("*.js"))
            and d.relative_to(args.web_static / "src")
            .as_posix()
            .split("/", maxsplit=1)[0]
            not in EXEMPT_SRC_DIRS
        )
        hints = registered_name_hints(
            args.web_static, [rel for rel, _f, _l in uncovered]
        )
        for rel, files, lines in uncovered:
            hint = hints.get(rel)
            suffix = f'  <- exercised via "{hint}"' if hint else ""
            print(f"  {rel:58s} {files:>3} js {lines:>6} lines{suffix}")
        print(
            f"\n{len(uncovered)} of {total} JS-bearing directories have no "
            f"addressable suite (report, not a contract — see contract A)"
        )
        if hints:
            print(
                f"  of those, {len(hints)} ARE exercised — a suite names the registry "
                f"key they publish, which no path can show.\n"
                f"  {len(uncovered) - len(hints)} have no handle of any kind; those are "
                f"the coverage candidates."
            )
        return 0

    new, stale = find_drift(args.web_static, *pins)

    if args.json:
        print(
            json.dumps(
                {"new": [asdict(f) for f in new], "stale": [asdict(f) for f in stale]},
                indent=2,
            )
        )
    else:
        print("JS suite/source parity check (drift-zero)")
        if foreign:
            print(f"scanning {args.web_static} — foreign tree, pins not applied")
        print("=" * 64)
        for contract in ("layer-coverage", "orphan-test-dir"):
            hits = [f for f in new if f.contract == contract]
            status = f"{len(hits)} new" if hits else "0 new"
            print(f"[{'FAIL' if hits else '  ok'}] {contract}: {status}")
            for f in hits:
                print(f)
        if stale:
            print(f"\n[FAIL] {len(stale)} pinned entr(y/ies) now CLEAN — unpin them:")
            for f in stale:
                print(f)
        print("-" * 64)
        if not new and not stale:
            print("\nNo new parity drift. ✓")
        if not foreign:
            print(
                f"\nKnown/tolerated: {len(KNOWN_UNCOVERED_LAYERS)} uncovered layer(s), "
                f"{len(KNOWN_ORPHAN_TEST_DIRS)} orphan test dir(s)"
            )

    return 1 if ((new or stale) and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
