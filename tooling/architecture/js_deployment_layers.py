"""Drift-zero gate for the *deployment-context* layering used by mail & friends.

``js_layer_check`` locks ``web``'s Feature-Sliced layering: top-level directory
prefixes in one addon, ordered by concern (``core`` < ``ui`` < ... <
``webclient``). This gate locks a different rule, of a different shape, in a
different set of addons.

``mail`` organises its client code by **where the code runs**, not by what it
does. Every leaf directory carries a layer name as a path *segment* —
``core/common/``, ``chatter/web_portal/``, ``discuss/core/public/`` — and that
segment decides which asset bundles the file lands in. ``mail``'s own
``machine_doc_v1/ARCHITECTURE.md`` calls this "the module's most distinctive
architectural trait"; ``CONVENTIONS.md`` states the cardinal rule as "``common/``
must never import from a higher layer".

Nothing enforced it. Every ``no-restricted-imports`` block in
``eslint.config.mjs`` is scoped ``**/web/static/src/**``, and the twelve
addon-scoped gates in this directory all resolve
``ROOT / "addons" / "web" / "static" / "src"``. The rule lived in prose only,
in the addon with the second-largest JS tree in the repo.

The failure it prevents is not a style problem. ``common/`` ships in
``mail.assets_public``, the standalone bundle for the anonymous discuss page,
which contains no ``web/`` layer at all. A ``common/`` file importing a ``web/``
module resolves to ``undefined`` at runtime on that page — and only on that
page, which no unit suite loads.

**The contract is bundle subset, not a rank.** A linear ordering is the obvious
model and it is wrong: ``web`` and ``public`` are mutually exclusive deployment
targets, and ``public_web`` and ``web_portal`` overlap only in the backend, so
neither pair can be ordered against the other. The true rule falls out of asset
membership, and is exactly what ``ASSET_LAYERS.md`` tabulates:

    common      ships in {backend, public, portal}
    public_web  ships in {backend, public}
    web_portal  ships in {backend, portal}
    web         ships in {backend}
    public      ships in {public}

    A may import B  <=>  bundles(A) is a subset of bundles(B)

"B must ship everywhere A ships." Read the other way, an import is a promise
that the target is present, so the target has to be present in every context the
importer reaches. This forbids ``common -> anything``, ``web <-> public``, and
``public_web <-> web_portal`` (each ships somewhere the other does not), while
allowing every edge the tree actually has.

Measured over ``addons/`` + ``odoo/addons/`` when this gate was written, all 199
cross-layer edges satisfy it and none violate it:

    web -> common 100 | public_web -> common 66 | web -> public_web 16
    web_portal -> common 5 | public -> public_web 6 | public -> common 4
    web -> web_portal 2

So this pins a property the tree holds today, which is the cheapest moment to
pin one. ``KNOWN_VIOLATIONS`` is empty and should stay that way.

**Scope is every addon that uses the convention**, not ``mail`` alone: the
satellites layer their own code the same way and import across addon boundaries
(``im_livechat/common`` -> ``@mail/core/common``), so a gate that watched only
``mail`` would miss the same bug one directory over. Addons opt in by having at
least one layer-named directory; there is no list to maintain.

Usage::

    python tooling/architecture/js_deployment_layers.py            # report
    python tooling/architecture/js_deployment_layers.py --check    # CI, exit 1
    python tooling/architecture/js_deployment_layers.py --json

Type-only imports do not count: ``collect_imports`` is the shared parser, so
JSDoc ``@import`` tags and ``import("...")`` inside comments create no edge.
"""

import argparse
import json
import posixpath
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root
from js_imports import collect_imports

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_deployment_layers")
ADDON_ROOTS: tuple[Path, ...] = (ROOT / "addons", ROOT / "odoo" / "addons")

# Vendored bundles and pre-layering code are not governed. Mirrors
# js_cycle_check's exclusions.
EXCLUDED_PARTS = frozenset({"lib", "legacy", "__pycache__"})

# The deployment contexts a layer's files are served in. Names are the asset
# bundles' audiences, not bundle ids: `portal` covers the standalone
# `mail.assets_*_web_portal` bundles, `public` the `mail.assets_public` page.
BACKEND, PUBLIC, PORTAL = "backend", "public", "portal"

LAYER_BUNDLES: dict[str, frozenset[str]] = {
    "common": frozenset({BACKEND, PUBLIC, PORTAL}),
    "public_web": frozenset({BACKEND, PUBLIC}),
    "web_portal": frozenset({BACKEND, PORTAL}),
    "web": frozenset({BACKEND}),
    "public": frozenset({PUBLIC}),
}


@dataclass(frozen=True)
class Known:
    """A pre-existing, tolerated violation, pinned with its remediation.

    ``module`` is ``<addon>/<path-under-static/src>`` without the ``.js``;
    ``imports`` is the resolved target module id in the same shape.
    """

    module: str
    imports: str
    reason: str


# The tree is clean. An entry here is visible debt on a rule whose failure mode
# is an undefined symbol on the anonymous discuss page.
KNOWN_VIOLATIONS: tuple[Known, ...] = ()


@dataclass(frozen=True)
class Violation:
    module: str
    module_layer: str
    imports: str
    imports_layer: str
    path: str
    lineno: int
    missing: tuple[str, ...]
    """Contexts the importer ships in that the target does not — the reason."""


def layer_of(rel: str) -> str | None:
    """The layer segment of a ``static/src``-relative path, if any.

    The first matching segment wins. Paths carry at most one in practice
    (``discuss/core/public_web/x.js``); a hypothetical ``web/common/`` would
    resolve to ``web``, which is the conservative reading — the outer directory
    is the one the manifest globs on.
    """
    for part in rel.split("/"):
        if part in LAYER_BUNDLES:
            return part
    return None


def addon_src_dirs() -> dict[str, Path]:
    """``{addon name: static/src}`` for every addon present, first root wins."""
    dirs: dict[str, Path] = {}
    for root in ADDON_ROOTS:
        if not root.is_dir():
            continue
        for addon in sorted(root.iterdir()):
            src = addon / "static" / "src"
            if src.is_dir() and addon.name not in dirs:
                dirs[addon.name] = src
    return dirs


def iter_source_files() -> list[tuple[str, Path, Path]]:
    """``[(addon, src_root, path)]`` for files that sit in a governed layer."""
    out: list[tuple[str, Path, Path]] = []
    for addon, src in addon_src_dirs().items():
        for path in sorted(src.rglob("*.js")):
            rel_parts = path.relative_to(src).parts
            if EXCLUDED_PARTS.intersection(rel_parts):
                continue
            if layer_of(path.relative_to(src).as_posix()) is None:
                continue
            out.append((addon, src, path))
    return out


# Scopes that look like an addon prefix but are not one. `@odoo/owl` is the
# framework runtime, not `addons/odoo/static/src`; without this it resolves to a
# module id whose first segment happens to be a directory name.
NON_ADDON_SCOPES = frozenset({"odoo"})


def resolve(
    spec: str, addon: str, rel: str, addons: frozenset[str] | None = None
) -> str | None:
    """Import specifier -> ``<addon>/<path>`` module id, or ``None``.

    ``None`` for anything that is not an addon's ``static/src`` module: a bare
    package, ``@odoo/owl``, ``@web/../lib/...``, or a relative path that climbs
    out of the tree.

    ``addons`` restricts the accepted prefixes to addons that exist. It is
    optional so the function stays unit-testable without a tree; when omitted
    only the static ``NON_ADDON_SCOPES`` filter applies, which is enough because
    an unknown prefix cannot carry a governed layer anyway.
    """
    if spec.startswith("."):
        # posixpath, not Path: pure specifier arithmetic on module ids, with no
        # filesystem or symlink semantics wanted.
        target = posixpath.normpath(posixpath.join(posixpath.dirname(rel), spec))
        if target.startswith(".."):
            return None
        return f"{addon}/{target.removesuffix('.js')}"
    if spec.startswith("@"):
        other, _, target = spec[1:].partition("/")
        if not target or target.startswith("../"):
            return None
        if other in NON_ADDON_SCOPES:
            return None
        if addons is not None and other not in addons:
            return None
        return f"{other}/{target.removesuffix('.js')}"
    return None


def _is_known(module: str, target: str) -> bool:
    return any(k.module == module and k.imports == target for k in KNOWN_VIOLATIONS)


def check(
    files: list[tuple[str, Path, Path]] | None = None,
) -> tuple[list[Violation], list[Violation]]:
    """Return ``(new_violations, known_violations)``.

    ``files`` lets the caller pass the walk it already did, so the reported
    "files scanned" describes the walk that was actually checked.
    """
    new: list[Violation] = []
    known: list[Violation] = []
    selected = files if files is not None else iter_source_files()
    addons = frozenset(a for a, _, _ in selected)
    for addon, src, path in selected:
        rel = path.relative_to(src).as_posix()
        src_layer = layer_of(rel)
        src_bundles = LAYER_BUNDLES[src_layer]
        module = f"{addon}/{rel.removesuffix('.js')}"
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:  # pragma: no cover
            print(f"warning: could not read {path}: {exc}", file=sys.stderr)
            continue
        for spec, lineno in collect_imports(text):
            target = resolve(spec, addon, rel, addons)
            if target is None:
                continue
            target_layer = layer_of(target.partition("/")[2])
            if target_layer is None:
                continue
            missing = src_bundles - LAYER_BUNDLES[target_layer]
            if not missing:
                continue
            v = Violation(
                module=module,
                module_layer=src_layer,
                imports=target,
                imports_layer=target_layer,
                # relative_to would raise for a tree outside the repo, which the
                # unit tests build in tmp_path; the absolute path is a fine
                # fallback and never happens in a real run.
                path=str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
                lineno=lineno,
                missing=tuple(sorted(missing)),
            )
            (known if _is_known(module, target) else new).append(v)
    return new, known


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any NEW violation"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    files = iter_source_files()
    scanned = len(files)
    # A gate that finds no inputs must say so rather than scan nothing and
    # report success. See test_every_gate_refuses_an_empty_tree.
    if not scanned:
        parser.error(
            "no layered JS sources under "
            f"{', '.join(str(r) for r in ADDON_ROOTS)} — the scan reached nothing"
        )

    new, known = check(files)

    if args.json:
        print(
            json.dumps(
                {
                    "new": [v.__dict__ for v in new],
                    "known": [v.__dict__ for v in known],
                    "files_scanned": scanned,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1 if (args.check and new) else 0

    print("JS deployment-layer check (drift-zero)")
    print("=" * 64)
    print()
    if not new:
        print("No cross-layer import reaches a layer that ships less. ✓")
    else:
        print(f"{len(new)} NEW violation(s):")
        for v in new:
            print(f"\n  {v.path}:{v.lineno}")
            print(f"    {v.module_layer}/ imports {v.imports_layer}/ — {v.imports}")
            print(
                f"    {v.imports_layer}/ is absent from: {', '.join(v.missing)}; "
                f"the import resolves to undefined there."
            )
    if known:
        print(f"\n{len(known)} known violation(s) tolerated (tracked debt):")
        for v in known:
            print(f"  {v.module} -> {v.imports}")
    print(f"\nLayered files scanned: {scanned}")
    print(f"New: {len(new)}   Known/tolerated: {len(known)}")
    return 1 if (args.check and new) else 0


if __name__ == "__main__":
    raise SystemExit(main())
