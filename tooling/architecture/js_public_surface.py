import argparse
import json
import sys
import textwrap
from pathlib import Path

from js_imports import imported_specifiers

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0020"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_public_surface")

GOVERNED_ADDONS = ("web", "mail")
DEFAULT_ADDON = "web"

WEB = ROOT / "addons" / "web"


def addon_root(addon: str = DEFAULT_ADDON) -> Path:
    return WEB if addon == DEFAULT_ADDON else ROOT / "addons" / addon


def pin_path(addon: str = DEFAULT_ADDON) -> Path:
    if addon == DEFAULT_ADDON:
        return PINNED
    return Path(__file__).resolve().parent / f"public_surface_{addon}.txt"


def specifier_prefix(addon: str = DEFAULT_ADDON) -> str:
    return f"@{addon}/"


PINNED = Path(__file__).resolve().parent / f"public_surface_{DEFAULT_ADDON}.txt"

CONSUMER_ROOTS = (
    ("odoo", ROOT),
    ("enterprise", ROOT.parent / "enterprise"),
    ("agromarin", ROOT.parent / "agromarin"),
    ("design-themes", ROOT.parent / "design-themes"),
)
# Imported by design-themes files that no bundle loads. This fork dropped
# `@web/legacy/*` outright and moved translation out of `core/l10n/`, but
# design-themes is vendored from upstream, where both still exist. The three
# importers -- theme_common's `old_snippets/` and theme_test_custo -- are
# declared in no `assets` manifest key and named by no `ir.asset` row (checked
# against marin190 on 2026-08-22, with theme_common installed), so they are
# dead files rather than a broken bundle. Accounted here rather than fixed:
# the drift belongs to the vendored repo, not to this one.
KNOWN_UNRESOLVED: frozenset[str] = frozenset(
    {
        "@web/core/l10n/translation",
        "@web/legacy/js/core/dom",
        "@web/legacy/js/public/public_widget",
    }
)


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


def _is_addon_internal(path: Path, addon: str = DEFAULT_ADDON) -> bool:

    try:
        path.relative_to(addon_root(addon))
    except ValueError:
        return False
    return True


def _is_web_internal(path: Path) -> bool:
    return _is_addon_internal(path, "web")


def measure_detailed(
    consumer_roots=CONSUMER_ROOTS,
    addon: str = DEFAULT_ADDON,
) -> dict[str, dict[str, tuple[int, int]]]:

    found: dict[str, dict[str, list[int]]] = {}
    for name, root in _named_roots(consumer_roots):
        for path in root.rglob("*.js"):
            text = path.as_posix()
            if "/static/lib/" in text or "/node_modules/" in text:
                continue
            if _is_addon_internal(path, addon):
                continue
            try:
                source = path.read_text(encoding="utf8")
            except UnicodeDecodeError, OSError:
                continue
            slot = 1 if "/static/tests/" in text else 0
            prefix = specifier_prefix(addon)
            for spec in imported_specifiers(source):
                if not spec.startswith(prefix) or spec.startswith(f"{prefix}../"):
                    continue
                found.setdefault(spec, {}).setdefault(name, [0, 0])[slot] += 1
    return {
        spec: {scope: (prod, test) for scope, (prod, test) in scopes.items()}
        for spec, scopes in found.items()
    }


def measure_by_scope(
    consumer_roots=CONSUMER_ROOTS, addon: str = DEFAULT_ADDON
) -> dict[str, tuple[int, int]]:
    return {
        spec: (
            sum(prod for prod, _ in scopes.values()),
            sum(test for _, test in scopes.values()),
        )
        for spec, scopes in measure_detailed(consumer_roots, addon).items()
    }


def measure(
    consumer_roots=CONSUMER_ROOTS, addon: str = DEFAULT_ADDON
) -> dict[str, int]:
    return {
        spec: prod + test
        for spec, (prod, test) in measure_by_scope(consumer_roots, addon).items()
    }


def provenance(
    detailed: dict[str, dict[str, tuple[int, int]]],
) -> dict[str, frozenset[str]]:
    return {spec: frozenset(scopes) for spec, scopes in detailed.items()}


def load_pinned(addon: str = DEFAULT_ADDON) -> dict[str, frozenset[str]]:

    pinned: dict[str, frozenset[str]] = {}
    path = pin_path(addon)
    if not path.is_file():
        return pinned
    for line in path.read_text(encoding="utf8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        spec, *tags = line.split()
        pinned[spec] = frozenset(tags)
    return pinned


def _scope_order(scope: str) -> tuple[int, str]:
    names = [name for name, _ in CONSUMER_ROOTS]
    return (names.index(scope) if scope in names else len(names), scope)


def write_pinned(
    measured_provenance: dict[str, frozenset[str]], addon: str = DEFAULT_ADDON
) -> None:
    paragraphs = (
        (
            f"The `@{addon}/*` specifiers imported from outside the {addon} "
            f"addon: {addon}'s public surface, as it is rather than as anyone "
            "designed it. Each entry names the consumer checkout(s) importing "
            "it — its provenance — and the gate judges only the scopes present "
            "in the environment, so a repo-alone CI checkout validates the "
            "`odoo` scope and the sibling repos' workflows validate theirs."
        ),
        (
            "Shrink-only, per scope. A specifier pinned for a scope that no "
            "longer imports it fails the gate until the entry is shrunk, so "
            "giving up surface is recorded; one imported from a scope it is "
            "not pinned for fails as new exposure there."
        ),
        (
            "Every entry is deliberately unclassified beyond provenance — see "
            "the module docstring on why most of this surface has no "
            "defensible tier yet."
        ),
    )
    header = (
        "\n#\n".join(
            textwrap.fill(
                p,
                width=72,
                initial_indent="# ",
                subsequent_indent="# ",
                break_on_hyphens=False,
                break_long_words=False,
            )
            for p in paragraphs
        )
        + "\n# Generated by tooling/architecture/js_public_surface.py --update"
        + f"{'' if addon == DEFAULT_ADDON else f' --addon {addon}'}.\n"
    )
    lines = [
        f"{spec}  {' '.join(sorted(scopes, key=_scope_order))}"
        for spec, scopes in sorted(measured_provenance.items())
    ]
    pin_path(addon).write_text(header + "\n".join(lines) + "\n", encoding="utf8")


def drift(
    measured_provenance: dict[str, frozenset[str]],
    pinned: dict[str, frozenset[str]],
    present_scopes: list[str],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:

    new: dict[str, list[str]] = {}
    gone: dict[str, list[str]] = {}
    for scope in present_scopes:
        measured_scope = {
            s for s, scopes in measured_provenance.items() if scope in scopes
        }
        pinned_scope = {s for s, tags in pinned.items() if not tags or scope in tags}
        grown = sorted(measured_scope - pinned_scope)
        shrunk = sorted(pinned_scope - measured_scope)
        if grown:
            new[scope] = grown
        if shrunk:
            gone[scope] = shrunk
    return new, gone


def unresolved(specifiers, addon: str = DEFAULT_ADDON) -> list[str]:

    src = addon_root(addon) / "static" / "src"
    prefix = specifier_prefix(addon)
    return sorted(
        spec
        for spec in specifiers
        if not (
            (src / f"{spec.removeprefix(prefix)}.js").is_file()
            or (src / spec.removeprefix(prefix) / "index.js").is_file()
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on drift")
    parser.add_argument("--update", action="store_true", help="rewrite the pin")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--addon",
        default=DEFAULT_ADDON,
        choices=GOVERNED_ADDONS,
        help="which addon's surface to measure and pin (default: web)",
    )
    args = parser.parse_args(argv)
    addon = args.addon

    if not (addon_root(addon) / "static" / "src").is_dir():
        parser.error(f"no {addon} addon at {addon_root(addon)}")

    present = [name for name, _ in _named_roots(CONSUMER_ROOTS)]
    absent = [name for name, _ in CONSUMER_ROOTS if name not in present]

    if args.update and absent:
        parser.error(
            "--update needs every consumer checkout present; missing: "
            + ", ".join(absent)
        )

    detailed = measure_detailed(CONSUMER_ROOTS, addon)
    if not detailed:
        parser.error("measured an empty surface — the scan reached nothing")
    measured_provenance = provenance(detailed)

    if args.update:
        write_pinned(measured_provenance, addon)
        print(f"wrote {pin_path(addon).name}: {len(measured_provenance)} specifier(s)")
        return 0

    pinned = load_pinned(addon)
    new, gone = drift(measured_provenance, pinned, present)

    dangling = set(unresolved(measured_provenance, addon))
    unexpected = sorted(dangling - KNOWN_UNRESOLVED)
    resolved = sorted(KNOWN_UNRESOLVED - dangling)

    by_scope = {
        spec: (
            sum(prod for prod, _ in scopes.values()),
            sum(test for _, test in scopes.values()),
        )
        for spec, scopes in detailed.items()
    }
    measured = {spec: prod + test for spec, (prod, test) in by_scope.items()}

    if args.json:
        print(
            json.dumps(
                {
                    "scopes_present": present,
                    "scopes_absent": absent,
                    "measured": len(detailed),
                    "test_only": sorted(
                        s for s, (prod, test) in by_scope.items() if prod == 0 and test
                    ),
                    "new": new,
                    "gone": gone,
                    "unresolved_unexpected": unexpected,
                    "unresolved_fixed": resolved,
                },
                indent=2,
            )
        )
        return 1 if ((new or gone or unexpected or resolved) and args.check) else 0

    print("JS public-surface ratchet (shrink-only, per consumer scope)")
    print("=" * 64)
    print(f"consumer scopes present: {', '.join(present)}")
    if absent:
        print(f"  absent, validated in their own CI: {', '.join(absent)}")
    print(f"measured {len(measured)} specifier(s) imported from outside {addon}")
    deep = sum(1 for s in measured if s.count("/") >= 3)
    test_only = sum(1 for prod, test in by_scope.values() if prod == 0 and test)
    print(f"  of which {deep} reach three or more segments deep")
    print(
        f"  {len(measured) - test_only} reached from production code, {test_only} only from tests"
    )
    for scope, specs in new.items():
        print(
            f"\n[FAIL] scope '{scope}': {len(specs)} NEW specifier(s) — the surface grew:"
        )
        for s in specs[:20]:
            print(f"    {s}  ({measured[s]} importer(s))")
        if len(specs) > 20:
            print(f"    … and {len(specs) - 20} more")
    for scope, specs in gone.items():
        print(
            f"\n[FAIL] scope '{scope}': {len(specs)} pinned specifier(s) no longer "
            f"imported from it — shrink the list:"
        )
        for s in specs[:20]:
            print(f"    {s}")
        if len(specs) > 20:
            print(f"    … and {len(specs) - 20} more")
    if unexpected:
        print(
            f"\n[FAIL] {len(unexpected)} specifier(s) resolve to no module in web — "
            f"these cannot load, and are not surface:"
        )
        for s in unexpected:
            print(f"    {s}  ({measured[s]} importer(s))")
        print("    Fix the import; do not pin it.")
    if resolved:
        print(
            f"\n[FAIL] {len(resolved)} known-unresolved specifier(s) no longer "
            f"dangle — shrink KNOWN_UNRESOLVED:"
        )
        for s in resolved:
            print(f"    {s}")
    print("-" * 64)
    if not new and not gone and not unexpected and not resolved:
        print(f"\nSurface unchanged across {len(present)} scope(s). ✓")
        if KNOWN_UNRESOLVED:
            print(
                f"  {len(KNOWN_UNRESOLVED)} known-unresolved specifier(s) carried "
                f"as debt (see R6)."
            )

    return 1 if ((new or gone or unexpected or resolved) and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
