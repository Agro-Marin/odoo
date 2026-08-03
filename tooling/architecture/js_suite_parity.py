"""Suite/source parity gate for the ``web`` addon's JavaScript tests.

HOOT derives a suite's identity from the **test** file's path, not from the path
of the source it exercises. So when source moves and its tests do not, the suite
id silently keeps pointing at the old shape. Nothing fails: the tests still run,
still pass, and still report green under their old id. What breaks is selecting
a module's tests by where its source lives.

The instance this gate was written for, now paid down: ``views/fields/`` became
a top-level ``fields/`` with seven subcategories while its 84 test files stayed
at ``static/tests/views/fields/``, so ``@web/fields`` — the obvious selector for
114 source files — resolved to **zero** suites and ``@web/views/fields`` to 84.
The suites have since moved to mirror the source, and ``fields`` is out of the
pinned set below so it cannot come back unnoticed.

Neither ESLint, the layer gate, the cycle gate, nor either typecheck lock can
see this class of drift, because no import is wrong and no file is missing.

Two contracts, both drift-zero:

  A. **Layer coverage.** Every top-level directory under ``static/src`` holding
     at least one ``.js`` file has at least one ``*.test.js`` under the same
     name in ``static/tests``. Catches "a whole layer became unaddressable".

  B. **No orphan test directories.** Every directory under ``static/tests``
     containing ``*.test.js`` has a counterpart directory under ``static/src``.
     Catches the same drift one level down, where it starts.

``KNOWN_*`` entries are today's debt, pinned so it cannot grow. They may only
shrink — a fixed entry that is still listed fails the gate exactly like a new
violation, so the list cannot rot into a permanent allowlist. ``EXEMPT_*`` is
different in kind: test infrastructure that mirrors no source by design and
never will.

Usage::

    python tooling/architecture/js_suite_parity.py            # human-readable report
    python tooling/architecture/js_suite_parity.py --check    # CI mode, exit 1 on drift
    python tooling/architecture/js_suite_parity.py --json     # machine-readable
"""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Repo root = the directory that contains ``odoo/`` and ``addons/``. This file
# lives at ``<root>/tooling/architecture/js_suite_parity.py``.
ROOT = Path(__file__).resolve().parent.parent.parent
WEB_STATIC = ROOT / "addons" / "web" / "static"

# Test infrastructure: mirrors no source directory by design. Not debt.
#   _framework  the HOOT harness itself (mock server, fixtures, setup)
#   helpers     assertions about those helpers
#   mock_server assertions about the mock ORM, which is harness code
#   tours       tour definitions, driven from Python, not a HOOT suite tree
EXEMPT_TEST_DIRS = frozenset({"_framework", "helpers", "mock_server", "tours"})

# Source directories that carry no JavaScript and so cannot own a suite.
EXEMPT_SRC_DIRS = frozenset({"scss", "@types"})

# Contract A debt: a source layer with no suite of its own name.
#   boot    main.js / start.js are covered indirectly via tests/env.test.js
KNOWN_UNCOVERED_LAYERS = frozenset({"boot"})

# Contract B debt: test directories with no same-path source directory. Each is
# the same drift as `fields`, caught smaller. The comment names where the source
# actually lives, so paying one down is a lookup rather than an investigation.
KNOWN_ORPHAN_TEST_DIRS = frozenset(
    {
        "interactions",  # -> public/interactions (public-page interactions)
        "l10n",  # -> core/l10n
        "modules",  # -> (root) module_loader.js + core/module_bridge.js
        "ui/notifications",  # -> ui/notification  (singular in src)
        "webclient/barcode",  # -> components/barcode
        "webclient/mobile",  # -> webclient/burger_menu and siblings
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
    """Top-level ``static/src`` directories mapped to their ``.js`` count."""
    src = web_static / "src"
    return {
        d.name: len(list(d.rglob("*.js")))
        for d in sorted(src.iterdir())
        if d.is_dir() and d.name not in EXEMPT_SRC_DIRS
    }


def _test_dirs_with_suites(web_static: Path) -> list[str]:
    """``static/tests`` directories holding at least one ``*.test.js``, as
    paths relative to ``tests/``. The tests root itself is excluded — files
    directly under it (``env.test.js``) mirror ``src`` root files by design."""
    tests = web_static / "tests"
    found = []
    for d in sorted(p for p in tests.rglob("*") if p.is_dir()):
        rel = d.relative_to(tests).as_posix()
        if rel.split("/")[0] in EXEMPT_TEST_DIRS:
            continue
        if any(d.glob("*.test.js")):
            found.append(rel)
    return found


# ``registerField("x", …)`` / ``registerFallbackField("x", …)`` and the generic
# ``registry.category("cat").add("x", …)``. These publish a name that arch and
# view specs resolve at runtime — the only handle a suite has on the module.
_REGISTRATION_RE = re.compile(
    r"""register(?:Fallback)?Field\(\s*["']([^"']+)["']"""
    r"""|category\(\s*["'][^"']+["']\s*\)\s*\.\s*add\(\s*["']([^"']+)["']""",
    re.VERBOSE,
)


def _registered_names(js_file: Path) -> set[str]:
    """Every registry key a source file publishes."""
    text = js_file.read_text(encoding="utf-8", errors="replace")
    return {m.group(1) or m.group(2) for m in _REGISTRATION_RE.finditer(text)}


def registered_name_hints(web_static: Path, directories: list[str]) -> dict[str, str]:
    """For each directory, any registry key it publishes that a suite names.

    The other half of ``uncovered_directories``. That function answers "has this
    directory a selector of its own"; this one answers "is it reached some other
    way" — the question a reader actually has when they see a directory listed,
    and the one whose absence turned a selectability report into a false
    coverage alarm.

    A hit is weak evidence: the name is quoted somewhere in the suites, which
    says the widget is exercised, not that it is well asserted. It is still far
    stronger than the path-shaped inference it replaces.

    Built once for the whole corpus — re-reading the suites per directory turned
    a sub-second report into a multi-second one.
    """
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
    """Every ``static/src`` directory holding JS that no suite addresses.

    A report, not a contract. Contract A is deliberately coarse — it asks only
    whether a whole *layer* became unaddressable — so this is what sits below
    its resolution: ``(path, js files, lines)`` for each directory reachable by
    no ``--test-tags`` selector of its own.

    A directory counts as addressed by either shape the tree actually uses: a
    mirrored ``tests/<path>/`` holding suites, or a sibling
    ``tests/<parent>/<name>.test.js``. Checking only the first reports ~2.5x
    the real number, which is how this measurement first went wrong.

    **This measures selectability, not coverage, and the two are easy to
    confuse.** A 2026-08-03 audit read this list as "untested" and concluded
    ``fields/specialized/user_groups`` — the ``res.users`` access-rights widget
    — was a security-adjacent coverage gap. It is exercised, by
    ``tests/webclient/res_user_group_ids_field.test.js``, which reaches it the
    only way a registry-driven widget can be reached: by naming it in an arch
    string (``<field widget="res_user_group_ids"/>``). No path and no import
    relate the two, so nothing here could see it — and the directory genuinely
    still has no selector of its own, which is what this function is about.

    ``registered_name_hints()`` supplies that missing half for the report, so a
    reader gets both facts instead of inferring the wrong one from this number.
    """
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
    """Returns ``(new_violations, stale_known_entries)``.

    Stale entries are pinned debt that has since been fixed. They fail the gate
    too: a shrink-only list that is never shrunk is an allowlist, and the whole
    point of pinning is that paying debt down is visible in review.

    The pinned sets are parameters rather than reads of the module constants so
    that a caller — a test over a synthetic tree, or a scan of a different
    checkout — is not silently judged against *this* checkout's debt.
    """
    known_uncovered = (
        KNOWN_UNCOVERED_LAYERS if known_uncovered is None else known_uncovered
    )
    known_orphans = KNOWN_ORPHAN_TEST_DIRS if known_orphans is None else known_orphans
    src, tests_root = web_static / "src", web_static / "tests"
    new: list[Finding] = []
    seen_uncovered: set[str] = set()
    seen_orphans: set[str] = set()

    # Contract A — every source layer owns a suite tree of its own name.
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

    # Contract B — every suite directory has a source directory behind it.
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
        # A gate that cannot find its inputs must say so rather than scan
        # nothing and report success.
        parser.error(f"no web static tree at {args.web_static}")

    # The pins describe THIS checkout's debt. Applied to a tree that is not this
    # checkout they are meaningless, and every one of them reports as "now
    # clean" — noise that buries the real findings for the tree actually asked
    # about. Scan a foreign tree against no pins, and say so.
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
