"""Public-surface ratchet for a governed addon's JavaScript.

Addon-parameterised via ``--addon``, defaulting to ``web``; each governed addon
has its own pin file (``public_surface_<addon>.txt``). ``mail`` is the second,
added because it has the same property and the second-largest JS tree in the
repo: **93 specifiers reached from outside it, 88 from production code and 90
three or more segments deep** — two independent partitions of the 93 (5 are
test-only; a different 3 are shallow, and those three are exactly `@mail/model/*`,
the one top-level directory left without a deployment-layer suffix). Everything
the rest of this
docstring says about `web` — no declared boundary, moves priced in downstream
edits, the pin as the worklist — is true of `mail` verbatim.

`web` has no declared API. Every file under ``static/src`` is reachable as
``@web/<path>``, and **327 distinct specifiers are imported from outside the
addon today** — 276 of them three or more segments deep, i.e. into a module's
internals rather than at a layer's edge. (A raw grep says 331; the four extra
are JSDoc type references, which this gate strips for the reason given on
``measure_by_scope``.)

Of the 327, **320 are reached from production code and 7 only from tests**. Both
are pinned — moving a file breaks a suite exactly as thoroughly as it breaks a
feature — but they are reported apart, because only the first is a statement
about what `web` owes anyone. ``webclient/clickbot/clickbot`` is on this list
because one `enterprise` test reads its ``SUCCESS_SIGNAL``; whatever the right
answer for it is, it is not an API decision.

That is the reason every internal move is expensive. Relocating the misfiled
half of ``services/`` cost 338 downstream edits; dissolving the rest cost about
500 more, across four separately-versioned repositories that cannot be committed
atomically. None of that expense came from the refactor being wrong. It came
from there being no boundary between what `web` publishes and what it merely
contains.

This gate does not invent the boundary — that is a design decision, and a large
one. It does the thing that has to come first and gets harder every day it
waits: **pin what the surface is, so it can only shrink.** Adding a new deep
import into `web` becomes a visible edit to this list rather than a silent
widening, and the list is then the worklist for whoever draws the real boundary.

Contract: per consumer scope, the pinned set and the measured set must be equal.

  * a specifier imported but **not pinned for that scope** is new surface —
    fail;
  * a specifier pinned for a scope but **no longer imported from it** is
    surface that has been given up — fail until the list is shrunk, so the win
    is recorded rather than quietly re-spendable.

That second half is what makes this a ratchet rather than an allowlist, and it
is the same drift-zero shape as every other gate in this directory.

**The pin is environment-honest.** Each entry records its provenance — which
consumer checkout(s) actually import it (``odoo``, ``enterprise``,
``agromarin``, ``design-themes``) — and ``--check`` judges only the scopes
whose checkout is present. The first version pinned bare membership measured
over the full workspace, which made the gate *unrunnable anywhere but the full
workspace*: repo-alone CI checks out this repo without its siblings, 27+
pinned specifiers have sibling-only importers, and every one of them fired
"gone" there — a blocking step that mathematically could not pass. Now a
repo-alone run validates the ``odoo`` scope (its gone-detection scoped to it),
the sibling repos' own architecture workflows check out this repo alongside
and validate their scopes, and the full workspace validates everything. The
shrink-only philosophy is intact *per scope*: an import appearing in a scope
it was not pinned for is growth there, even if another scope already reaches
the same specifier.

**The surface is a power law, and that is not enough to classify it.** Of the
12,544 import sites, 17 specifiers carry 69% while 105 have one or two importers
between them and carry 1.1%. That distribution invites a threshold, and a
threshold is wrong here.

Those 105 were briefly marked ``internal`` on exactly that reasoning. Reading
what the consumers actually do retracted it: ``UrlField`` is subclassed by
``website`` and ``hr_contract_salary``, which is the documented way to extend a
field widget; ``Collapse`` is reused by ``lunch``; ``NameAndSignature`` by
``sign`` and ``portal``. Twenty-four of the 105 are field widgets — the single
most extension-shaped thing `web` ships — and seventeen more are a module's own
face (``dropzone/dropzone``, ``offcanvas/offcanvas``, ``navbar/navbar``).

**Fan-in cannot distinguish "public but niche" from "private but reached."**
Two importers is what a legitimate component with modest demand looks like, and
also what a leak looks like. The real distinction is by role — primitive,
declared extension point, or incidental internal — and role does not correlate
with count anywhere in this distribution: the middle runs 54, 53, 53, 53, 50,
49, 49 with primitives, extension points and internals interleaved throughout.

So no tier is asserted. Beyond provenance — which is measured fact, not
judgement — the pin is membership-only, which is sound on its own: the surface
cannot grow or silently shrink. A per-specifier ``internal:N`` tier existed
here for a while, populated by nobody — no entry ever used it — and was
removed; if per-case judgements ever want a tier column, it should be
reintroduced by someone deciding, never by this tool inferring. A count is
evidence for that conversation, not a substitute for it.

`web`'s own imports of `@web/...` are NOT surface: a module importing its own
addon is internal by definition, and counting it would make the list track the
tree's size rather than its exposure. Nor is ``@web/../tests/...``, the
documented escape hatch by which other addons reach web's test helpers.

Usage::

    python tooling/architecture/js_public_surface.py                     # report
    python tooling/architecture/js_public_surface.py --check             # CI, exit 1
    python tooling/architecture/js_public_surface.py --update            # rewrite the pin
    python tooling/architecture/js_public_surface.py --json
    python tooling/architecture/js_public_surface.py --addon mail --check

``--update`` refuses to run unless every consumer checkout is present: an
update from a partial checkout could only erase the absent scopes' provenance,
and with it the record of what those consumers were owed.
"""

import argparse
import json
import sys
from pathlib import Path

from js_imports import imported_specifiers  # sys.path set by conftest.py

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_public_surface")

# The gate is addon-parameterised, defaulting to `web` so every existing call
# site, test and pin file keeps its meaning. `mail` is the second governed
# addon: 392 files, and the same "every internal path is reachable" property —
# 93 specifiers, 88 of them reached from production code. Adding a third addon is
# a `--addon` argument and a harvested pin file, not a code change.
GOVERNED_ADDONS = ("web", "mail")
DEFAULT_ADDON = "web"

# `WEB` and `PINNED` stay module-level, and the two resolvers below return them
# for the default addon rather than re-deriving. That is deliberate, not
# vestigial: the suite redirects the gate at a synthetic tree by monkeypatching
# these names, and a resolver that ignored them would silently point every test
# back at the real checkout. That is not hypothetical — it is what the first
# draft of this refactor did, and `--update` under test then overwrote the real
# `public_surface_web.txt` with two-line fixture data.
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

# Consumer scopes: (name, checkout root). The name is the provenance tag the
# pin file records, deliberately canonical rather than the on-disk directory
# name, so one pin file serves every clone layout.
#
# A scope whose checkout is absent is SKIPPED, not failed: repo-alone CI
# validates the `odoo` scope here, and each sibling repo's own architecture
# workflow (e.g. enterprise/.github/workflows/architecture.yml) checks out this
# repo alongside and validates its scope there. The full workspace — where
# `--update` must run — validates all of them at once.
CONSUMER_ROOTS = (
    ("odoo", ROOT),
    ("enterprise", ROOT.parent / "enterprise"),
    ("agromarin", ROOT.parent / "agromarin"),
    ("design-themes", ROOT.parent / "design-themes"),
)
KNOWN_UNRESOLVED: frozenset[str] = frozenset()


def _named_roots(consumer_roots) -> list[tuple[str, Path]]:
    """Normalise to ``(scope name, root)`` pairs for the roots present.

    Accepts the canonical ``(name, Path)`` form and, for tests building
    synthetic trees, bare paths — those take their directory name as scope.
    """
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
    """The governed addon's own imports of its own specifiers are not surface.

    A module importing its own addon is an internal edge; counting it would
    measure the tree's size rather than its exposure.
    """
    try:
        path.relative_to(addon_root(addon))
    except ValueError:
        return False
    return True


def _is_web_internal(path: Path) -> bool:
    """Back-compatible alias for the `web` default."""
    return _is_addon_internal(path, "web")


def measure_detailed(
    consumer_roots=CONSUMER_ROOTS,
    addon: str = DEFAULT_ADDON,
) -> dict[str, dict[str, tuple[int, int]]]:
    """``{specifier: {scope: (production importers, test importers)}}``.

    The one walk everything else derives from: which specifiers are imported
    from outside `web`, from which consumer checkout, from production code or
    from tests. Absent checkouts contribute nothing — and are therefore never
    judged.

    Only real imports count, which the shared parser decides. Two things this
    excludes are worth naming because a regex over ``"@web/..."`` string
    literals — what this used — included both. A JSDoc ``@import`` names a
    module without depending on it: moving the target breaks the *type*, which
    the typecheck locks already own, not anyone's runtime. And a string that
    merely looks like a specifier is not one at all: ``@web/core/l10n/
    translationLoaded`` is a bus event name, and it was on this list.

    A test importer is still surface — moving the file breaks it, and a broken
    suite is exactly as broken as a broken feature — so both halves are pinned.
    They are counted apart because they answer different questions: production
    importers say what `web` owes other modules, test importers say what its
    internals happen to be observable from. `webclient/clickbot/clickbot` is
    reached only by an `enterprise` test; that is not an API decision.
    """
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
    """``{specifier: (production importers, test importers)}`` outside `web`,
    summed over the consumer checkouts present. See :func:`measure_detailed`.
    """
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
    """``{specifier: importing files}`` over every consumer outside `web`."""
    return {
        spec: prod + test
        for spec, (prod, test) in measure_by_scope(consumer_roots, addon).items()
    }


def provenance(
    detailed: dict[str, dict[str, tuple[int, int]]],
) -> dict[str, frozenset[str]]:
    """``{specifier: scopes importing it}`` — what the pin records."""
    return {spec: frozenset(scopes) for spec, scopes in detailed.items()}


def load_pinned(addon: str = DEFAULT_ADDON) -> dict[str, frozenset[str]]:
    """``{specifier: pinned scopes}``.

    A line is ``<specifier>  <scope> <scope>...``. A tagless line — the
    pre-provenance format — pins the specifier for EVERY scope: that is what
    bare membership measured over the full workspace actually asserted, and
    reading it any narrower would silently drop pins on upgrade.
    """
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
    """Rewrite the pin from the measured surface, sorted, with provenance."""
    header = (
        f"# The `@{addon}/*` specifiers imported from outside the {addon} addon:\n"
        f"# {addon}'s public surface, as it is rather than as anyone designed it.\n"
        "# Each\n"
        "# entry names the consumer checkout(s) importing it — its provenance —\n"
        "# and the gate judges only the scopes present in the environment, so\n"
        "# a repo-alone CI checkout validates the `odoo` scope and the sibling\n"
        "# repos' workflows validate theirs.\n"
        "#\n"
        "# Shrink-only, per scope. A specifier pinned for a scope that no\n"
        "# longer imports it fails the gate until the entry is shrunk, so\n"
        "# giving up surface is recorded; one imported from a scope it is not\n"
        "# pinned for fails as new exposure there.\n"
        "#\n"
        "# Every entry is deliberately unclassified beyond provenance — see the\n"
        "# module docstring on why most of this surface has no defensible tier\n"
        "# yet.\n"
        "# Generated by tooling/architecture/js_public_surface.py --update"
        f"{'' if addon == DEFAULT_ADDON else f' --addon {addon}'}.\n"
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
    """Per-scope drift, judged ONLY for the scopes present.

    Returns ``(new, gone)``: ``{scope: [specifier, ...]}``, scopes with no
    drift omitted. A pinned entry with no tags (legacy format) counts as
    pinned for every scope — see :func:`load_pinned`.
    """
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
    """The specifiers that resolve to no module in the governed addon.

    A specifier is a path into ``<addon>/static/src``: ``@web/a/b`` is ``a/b.js``,
    or ``a/b/index.js`` where the module publishes a face. One matching neither
    is not surface at all — it is an import that cannot load, recorded as
    surface because the harvest measures what consumers *write* rather than
    what `web` *publishes*. Nothing in the pin distinguishes the two, which is
    how three of them accumulated before this check existed.

    R6's Trap already stated the rule this enforces: treat a pinned specifier
    that resolves to no file as evidence the harvest was wrong rather than as
    surface to preserve.
    """
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
        # A gate that cannot find its inputs must say so rather than scan
        # nothing and report success.
        parser.error(f"no {addon} addon at {addon_root(addon)}")

    present = [name for name, _ in _named_roots(CONSUMER_ROOTS)]
    absent = [name for name, _ in CONSUMER_ROOTS if name not in present]

    if args.update and absent:
        # An update from a partial checkout can only erase the absent scopes'
        # provenance — the record of what those consumers are owed. Refused
        # before the scan: the answer cannot depend on what a partial scan sees.
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

    # Judged against the measurement, not the pin: an import that resolves to
    # nothing is wrong the moment it is written, and waiting for it to be
    # pinned is how the pin came to record three of them.
    dangling = set(unresolved(measured_provenance, addon))
    unexpected = sorted(dangling - KNOWN_UNRESOLVED)
    resolved = sorted(KNOWN_UNRESOLVED - dangling)

    # Everything below derives from the one walk already done.
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
