"""Layer-cohesion gate for the ``web`` addon's JavaScript source.

A top-level directory under ``static/src`` is a *layer*: the layer gate orders
them, the cycle gate keeps them acyclic. Neither asks the prior question —
whether the directory is a module at all, or just a name several unrelated files
were filed under.

The distinction is measurable. In a module, files depend on each other; the
directory holds together because its contents belong together. In a namespace
they do not: the files share a *mechanism* (they all call ``.add()``, they are
all "helpers") rather than a dependency structure, and the directory could be
dissolved without any import changing except its own path.

``services/`` was the live instance, and has since been dissolved. Of its 40
files, 19 had no import relationship with any sibling — 48%, against 21% for the
next worst layer — and once the 19 that registered no service were filed
elsewhere, the residue was 20 registered services with **zero** edges between
them: not a low-cohesion module, not a module.

**What this measures, and what it does not.** Those 20 are reached through
``useService()`` and import nothing, so they read as isolated wherever they
sit — filing each with the concern it serves spread them over their hosts and
lifted several fractions a few points (``ui`` 22% -> 26%) without anything
having got worse. The metric therefore detects the CONCENTRATION of
mechanism-grouped files, not their existence. That is the defect it was built
for: a namespace is what you get when the concentration is total.

Contract: **isolated fraction**. A file is *isolated* in its layer when no
sibling imports it and it imports no sibling. A layer whose isolated fraction
exceeds ``MAX_ISOLATED_FRACTION`` is reported.

Why that and not cohesion (internal / total edges): cohesion punishes a layer
for depending on the layers below it, which is what layers are for. ``core`` at
0.98 and ``model`` at 0.61 look healthy, but ``webclient`` (0.22), ``ui`` (0.24)
and ``components`` (0.24) sit at ``services``'s 0.11 without being namespaces —
they are thin over ``core`` by design. Isolation asks only about the inside, and
there the separation is clean.

Measured when the threshold was set, worst first::

    services   19/40  0.48   <- the namespace, since dissolved
    ui          6/27  0.22
    webclient  14/66  0.21
    components 13/70  0.19
    core      15/129  0.12
    ...
    model       0/44  0.00

The threshold is empirical, not principled: 0.35 sat above every layer that was
a module and below the one that was not. With ``services/`` gone there is no
upper anchor left to re-derive it from, so it now stands on the lower half
alone — every real layer is under it, and a directory of nothing but
registration-only files scores 1.00. Do not nudge it to make a failure go
away; a layer arriving at 0.35 means something was filed by mechanism again.

Usage::

    python tooling/architecture/js_layer_cohesion.py            # report
    python tooling/architecture/js_layer_cohesion.py --check    # CI, exit 1
    python tooling/architecture/js_layer_cohesion.py --json     # machine-readable
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from js_imports import imported_specifiers  # sys.path set by conftest.py

ROOT = Path(__file__).resolve().parent.parent.parent
WEB_STATIC = ROOT / "addons" / "web" / "static"

# Above every layer that is a module, below the one that is not. See the table
# in the module docstring before touching this.
MAX_ISOLATED_FRACTION = 0.35

# Below this a layer is too small for the fraction to mean anything: two files
# that do not import each other is not evidence of anything.
MIN_FILES = 8

# Carries no JavaScript, so it can hold no edges.
EXEMPT_LAYERS = frozenset({"scss", "@types"})

# Today's debt, pinned so it cannot grow. Shrink-only: an entry that is no
# longer isolated fails the gate exactly like a new one, so the list cannot rot
# into an allowlist.
# Empty: `services/` was the only entry and no longer exists. Each of its 20
# services now sits with the concern it serves, and "service-ness" lives where
# it always did — in the registration and in @types/services.d.ts.
KNOWN_LOW_COHESION: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Finding:
    contract: str
    path: str
    detail: str

    def __str__(self) -> str:
        return f"  {self.path:26s} {self.detail}"


def _resolve(spec: str, from_file: Path, src: Path) -> str | None:
    """A specifier to a path relative to ``src``, or None if it leaves the tree."""
    if spec.startswith("@web/"):
        target = src / spec[len("@web/") :]
    elif spec.startswith("."):
        target = (from_file.parent / spec).resolve()
    else:
        return None
    for candidate in (target, target.with_suffix(".js"), target / "index.js"):
        try:
            rel = candidate.relative_to(src)
        except ValueError:
            return None
        if candidate.is_file():
            return rel.as_posix()
    return None


def layer_stats(web_static: Path) -> dict[str, tuple[int, int]]:
    """``{layer: (files, isolated)}`` over ``static/src``'s top-level dirs."""
    src = web_static / "src"
    connected: dict[str, set[str]] = {}
    owned: dict[str, list[str]] = {}
    for path in sorted(src.rglob("*.js")):
        rel = path.relative_to(src).as_posix()
        parts = rel.split("/")
        if len(parts) < 2 or parts[0] in EXEMPT_LAYERS:
            continue
        owned.setdefault(parts[0], []).append(rel)
        connected.setdefault(rel, set())
    for path in sorted(src.rglob("*.js")):
        rel = path.relative_to(src).as_posix()
        if rel not in connected:
            continue
        source = path.read_text(encoding="utf8", errors="replace")
        for spec in imported_specifiers(source):
            target = _resolve(spec, path, src)
            if target is None or target not in connected or target == rel:
                continue
            if target.split("/")[0] == rel.split("/")[0]:
                connected[rel].add(target)
                connected[target].add(rel)
    return {
        layer: (len(files), sum(1 for f in files if not connected[f]))
        for layer, files in sorted(owned.items())
    }


def find_drift(
    web_static: Path,
    known: frozenset[str] | None = None,
) -> tuple[list[Finding], list[Finding]]:
    """Returns ``(new_violations, stale_known_entries)``.

    ``known`` is a parameter rather than a read of the module constant so a
    caller scanning a synthetic or foreign tree is not judged against *this*
    checkout's debt.
    """
    known = KNOWN_LOW_COHESION if known is None else known
    new: list[Finding] = []
    seen: set[str] = set()
    for layer, (total, isolated) in layer_stats(web_static).items():
        if total < MIN_FILES:
            continue
        fraction = isolated / total
        if fraction <= MAX_ISOLATED_FRACTION:
            continue
        seen.add(layer)
        if layer not in known:
            new.append(
                Finding(
                    "isolated-fraction",
                    f"src/{layer}/",
                    f"{isolated}/{total} files ({fraction:.0%}) import no sibling "
                    f"— over {MAX_ISOLATED_FRACTION:.0%}; a namespace, not a layer",
                )
            )
    stale = [
        Finding(
            "stale-known",
            f"src/{layer}/",
            "now cohesive — remove from KNOWN_LOW_COHESION",
        )
        for layer in sorted(known - seen)
    ]
    return new, stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--table", action="store_true", help="print every layer")
    parser.add_argument("--web-static", type=Path, default=WEB_STATIC)
    args = parser.parse_args(argv)

    src = args.web_static / "src"
    scanned = sum(1 for _ in src.rglob("*.js")) if src.is_dir() else 0
    # A gate that finds no inputs must say so rather than scan nothing and
    # report success. Testing only that `src/` exists is not that check: 61aa19e2712
    # swept this directory for the fault and cleared this gate, because an absent
    # tree does refuse. A tree that is present and empty does not — and that is the
    # reachable case, since an over-broad exclude empties the file list while
    # leaving the directory (tsconfig.json's `**/l10n*` did exactly that).
    if not scanned:
        parser.error(f"no JS sources under {src} — the scan reached nothing")

    foreign = args.web_static.resolve() != WEB_STATIC.resolve()
    new, stale = find_drift(args.web_static, frozenset() if foreign else None)

    if args.json:
        stats = {
            layer: {"files": t, "isolated": i, "fraction": round(i / t, 4)}
            for layer, (t, i) in layer_stats(args.web_static).items()
        }
        print(
            json.dumps(
                {
                    "layers": stats,
                    "new": [asdict(f) for f in new],
                    "stale": [asdict(f) for f in stale],
                },
                indent=2,
            )
        )
        return 1 if ((new or stale) and args.check) else 0

    print("JS layer-cohesion check (drift-zero)")
    if foreign:
        print(f"scanning {args.web_static} — foreign tree, pins not applied")
    print("=" * 64)
    if args.table:
        for layer, (total, isolated) in sorted(
            layer_stats(args.web_static).items(), key=lambda kv: -kv[1][1] / kv[1][0]
        ):
            mark = (
                " "
                if total < MIN_FILES
                else ("!" if isolated / total > MAX_ISOLATED_FRACTION else " ")
            )
            print(
                f" {mark} {layer:12s} {isolated:3d}/{total:<4d} {isolated / total:5.0%}"
            )
        print("-" * 64)
    status = f"{len(new)} new" if new else "0 new"
    print(f"[{'FAIL' if new else '  ok'}] isolated-fraction: {status}")
    for f in new:
        print(f)
    if stale:
        print(f"\n[FAIL] {len(stale)} pinned entr(y/ies) now COHESIVE — unpin them:")
        for f in stale:
            print(f)
    print("-" * 64)
    if not new and not stale:
        print("\nNo new cohesion drift. ✓")
    if not foreign:
        print(f"\nKnown/tolerated: {len(KNOWN_LOW_COHESION)} low-cohesion layer(s)")

    return 1 if ((new or stale) and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
