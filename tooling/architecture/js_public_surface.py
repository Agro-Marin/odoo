"""Public-surface ratchet for the ``web`` addon's JavaScript.

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

Contract: the pinned set and the measured set must be equal.

  * a specifier imported but **not pinned** is new surface — fail;
  * a specifier pinned but **no longer imported** is surface that has been given
    up — fail until the list is shrunk, so the win is recorded rather than
    quietly re-spendable.

That second half is what makes this a ratchet rather than an allowlist, and it
is the same drift-zero shape as every other gate in this directory.

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

So no tier is asserted. The pin is membership-only, which is sound on its own:
the surface cannot grow or silently shrink. The ``internal:N`` mechanism below
is kept, and tested, because per-case judgements will want it — but it is
populated by someone deciding, never by this tool inferring. A count is evidence
for that conversation, not a substitute for it.

`web`'s own imports of `@web/...` are NOT surface: a module importing its own
addon is internal by definition, and counting it would make the list track the
tree's size rather than its exposure. Nor is ``@web/../tests/...``, the
documented escape hatch by which other addons reach web's test helpers.

Usage::

    python tooling/architecture/js_public_surface.py            # report
    python tooling/architecture/js_public_surface.py --check    # CI, exit 1
    python tooling/architecture/js_public_surface.py --update   # rewrite the pin
    python tooling/architecture/js_public_surface.py --json
"""

import argparse
import json
import sys
from pathlib import Path

from js_imports import imported_specifiers  # sys.path set by conftest.py

ROOT = Path(__file__).resolve().parent.parent.parent
WEB = ROOT / "addons" / "web"
PINNED = Path(__file__).resolve().parent / "public_surface_web.txt"

# Repos scanned for consumers. Siblings are absent from a CI checkout; the
# pre-push hook covers those, exactly as cross_repo_coherence.py does.
CONSUMER_ROOTS = (
    ROOT,
    ROOT.parent / "enterprise",
    ROOT.parent / "agromarin",
    ROOT.parent / "design-themes",
)


def _is_web_internal(path: Path) -> bool:
    try:
        path.relative_to(WEB)
    except ValueError:
        return False
    return True


def measure_by_scope(consumer_roots=CONSUMER_ROOTS) -> dict[str, tuple[int, int]]:
    """``{specifier: (production importers, test importers)}`` outside `web`.

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
    found: dict[str, list[int]] = {}
    for root in consumer_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.js"):
            text = path.as_posix()
            if "/static/lib/" in text or "/node_modules/" in text:
                continue
            if _is_web_internal(path):
                continue
            try:
                source = path.read_text(encoding="utf8")
            except UnicodeDecodeError, OSError:
                continue
            slot = 1 if "/static/tests/" in text else 0
            for spec in imported_specifiers(source):
                if not spec.startswith("@web/") or spec.startswith("@web/../"):
                    continue
                found.setdefault(spec, [0, 0])[slot] += 1
    return {spec: (prod, test) for spec, (prod, test) in found.items()}


def measure(consumer_roots=CONSUMER_ROOTS) -> dict[str, int]:
    """``{specifier: importing files}`` over every consumer outside `web`."""
    return {
        spec: prod + test
        for spec, (prod, test) in measure_by_scope(consumer_roots).items()
    }


def load_pinned() -> dict[str, int | None]:
    """``{specifier: frozen importer count}``; None for unmarked entries."""
    pinned: dict[str, int | None] = {}
    if not PINNED.is_file():
        return pinned
    for line in PINNED.read_text(encoding="utf8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        spec, _, marker = line.partition("\tinternal:")
        pinned[spec.strip()] = int(marker) if marker else None
    return pinned


def write_pinned(measured: dict[str, int], previous: dict[str, int | None]) -> None:
    """Rewrite the pin, keeping every tier decision already recorded.

    A specifier already present keeps its tier: --update refreshes an
    ``internal`` count but never promotes or demotes, so a considered decision
    is not undone by re-running the tool. A specifier seen for the first time
    arrives unclassified, because nothing this tool can measure decides it.
    """
    header = (
        "# The `@web/*` specifiers imported from outside the web addon: web's\n"
        "# public surface, as it is rather than as anyone designed it.\n"
        "#\n"
        "# Shrink-only. A specifier here that is no longer imported fails the\n"
        "# gate until it is removed, so giving up surface is recorded; one that\n"
        "# is imported and not here fails as new exposure.\n"
        "#\n"
        "# `<spec>\\tinternal:N` is a leak frozen at N importers: it may not gain\n"
        "# one without an explicit edit here, and closing one must be recorded.\n"
        "# A bare `<spec>` is deliberately unclassified — see the module\n"
        "# docstring on why most of this surface has no defensible tier yet.\n"
        "# Generated by tooling/architecture/js_public_surface.py --update.\n"
    )
    lines = []
    for spec in sorted(measured):
        # Never inferred. A specifier is `internal` because somebody decided it
        # is, and --update only carries that decision forward; one seen for the
        # first time arrives unclassified. Inferring the tier from the importer
        # count was tried and retracted — see the module docstring.
        tier = previous.get(spec)
        lines.append(f"{spec}\tinternal:{measured[spec]}" if tier is not None else spec)
    PINNED.write_text(header + "\n".join(lines) + "\n", encoding="utf8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on drift")
    parser.add_argument("--update", action="store_true", help="rewrite the pin")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not (WEB / "static" / "src").is_dir():
        # A gate that cannot find its inputs must say so rather than scan
        # nothing and report success.
        parser.error(f"no web addon at {WEB}")

    measured = measure()
    if not measured:
        parser.error("measured an empty surface — the scan reached nothing")

    previous = load_pinned()

    if args.update:
        write_pinned(measured, previous)
        internal = sum(1 for v in load_pinned().values() if v is not None)
        print(
            f"wrote {PINNED.name}: {len(measured)} specifier(s), "
            f"{internal} marked internal"
        )
        return 0

    pinned = previous
    new = sorted(set(measured) - set(pinned))
    gone = sorted(set(pinned) - set(measured))
    # A frozen leak that gained or lost an importer. Both directions fail: one
    # is the leak widening, the other a win that has to be recorded or it can
    # be re-spent for nothing.
    widened = sorted(
        (s, pinned[s], measured[s])
        for s in set(pinned) & set(measured)
        if pinned[s] is not None and pinned[s] != measured[s]
    )

    if args.json:
        print(
            json.dumps(
                {
                    "measured": len(measured),
                    "test_only": sorted(
                        s
                        for s, (prod, test) in measure_by_scope().items()
                        if prod == 0 and test
                    ),
                    "new": new,
                    "gone": gone,
                    "internal_drift": [
                        {"spec": s, "pinned": p, "measured": m} for s, p, m in widened
                    ],
                },
                indent=2,
            )
        )
        return 1 if ((new or gone or widened) and args.check) else 0

    print("JS public-surface ratchet (shrink-only)")
    print("=" * 64)
    print(f"measured {len(measured)} specifier(s) imported from outside web")
    deep = sum(1 for s in measured if s.count("/") >= 3)
    marked = sum(1 for v in pinned.values() if v is not None)
    by_scope = measure_by_scope()
    test_only = sum(1 for prod, test in by_scope.values() if prod == 0 and test)
    print(f"  of which {deep} reach three or more segments deep")
    print(
        f"  {len(measured) - test_only} reached from production code, {test_only} only from tests"
    )
    print(
        f"  {marked} marked internal (frozen leaks); {len(pinned) - marked} unclassified"
    )
    if new:
        print(f"\n[FAIL] {len(new)} NEW specifier(s) — the surface grew:")
        for s in new[:20]:
            print(f"    {s}  ({measured[s]} importer(s))")
        if len(new) > 20:
            print(f"    … and {len(new) - 20} more")
    if gone:
        print(
            f"\n[FAIL] {len(gone)} pinned specifier(s) no longer imported — shrink the list:"
        )
        for s in gone[:20]:
            print(f"    {s}")
        if len(gone) > 20:
            print(f"    … and {len(gone) - 20} more")
    if widened:
        print(f"\n[FAIL] {len(widened)} internal specifier(s) drifted:")
        for spec, was, now in widened[:20]:
            verb = "gained" if now > was else "lost"
            print(f"    {spec}  pinned {was}, now {now} ({verb} an importer)")
        if len(widened) > 20:
            print(f"    … and {len(widened) - 20} more")
    print("-" * 64)
    if not new and not gone and not widened:
        print("\nSurface unchanged. ✓")

    return 1 if ((new or gone or widened) and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
