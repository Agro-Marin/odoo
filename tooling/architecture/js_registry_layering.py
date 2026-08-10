"""Layering gate for the ``web`` addon's REGISTRY-mediated dependencies.

``js_layer_check.py`` resolves ``import`` specifiers, and it reports zero
violations. That is true and it is only half the graph: a dependency taken
through ``registry.category("services")`` is exactly as real, binds at runtime,
and is invisible to every import-reading gate in this directory.

The hole is not theoretical. ``core/utils/hooks.js`` imports nothing from
``@web/ui`` — its only first-party import is ``core/browser/feature_detection``
— so ``core-below-ui-components`` reports ``ok``. Yet ``useOwnedDialogs()``
(line 272) calls ``useService("dialog")``, whose producer is
``ui/dialog/dialog_service.js``. Written as an import that is a
``core -> ui`` edge the gate rejects on sight; routed through the registry it
passes. The contract is satisfied in letter and broken in fact.

This gate closes that half, under two contracts.

**A. services** — producers via ``registry.category("services").add("<name>")``,
consumers via ``useService("<name>")``, ``env.services.<name>``,
``services["<name>"]``. 32 pinned.

**B. keyed-lookup** — any category, but only ``.get("<literal>")``, resolved to
whichever module registered that key. 9 pinned entries covering 14 call sites
(a module naming the same key twice is one dependency), all
``fields``/``components`` naming a ``views/`` implementation.

**Why enumeration is NOT a violation, and naming an item is.** A reader that
*enumerates* a category depends on the contract, never on a producer:
``ui/main_components_container.js`` binds ``main_components`` and renders
whatever is registered, so ``webclient/loading_indicator`` registering into it
creates no dependency from ``ui`` on ``webclient``. That is inversion of control
working as intended, and it is the reason the registry exists. A reader doing
``.get("select_create")`` is doing the opposite: it names one implementation and
binds to it, which is a dependency on that module in everything but syntax.
Measuring reader×producer pairs instead of keyed lookups reports 79 where the
real figure is 14, and most of the 79 are the plugin pattern being punished for
working.

Both contracts apply **the same layer order** ``js_layer_check.py`` applies to
imports, so the gates cannot disagree about what "upward" means:

    core < ui < components < model < fields < search < views < webclient

``boot/``, ``public/`` and ``libs/`` sit outside the stack and are ungoverned,
matching ``js_layer_check``. ``test_js_registry_layering`` asserts this order
against that module's ``CONTRACTS``, so reordering layers there without
reordering them here fails rather than silently diverging.

**What the 32 pinned entries say.** 26 of them are one service, ``action``,
consumed from ``core`` upward. That is not 26 careless callers: ``doAction`` is
genuinely cross-cutting, and a rule broken 26 times by unrelated, reasonable
call sites is a misplaced contract rather than a crime wave. ``action``'s
implementation belongs in ``webclient/`` — it owns the breadcrumb stack, the
URL, the controller stack — but its consumer-facing *interface* does not. The
remediation is the one this fork already applied to the data layer with
``makeModelUIHooks``: publish the narrow surface low, leave the implementation
where it is. Each entry retired is a line deleted here.

Usage::

    python tooling/architecture/js_registry_layering.py           # report
    python tooling/architecture/js_registry_layering.py --check   # CI, exit 1 on new
    python tooling/architecture/js_registry_layering.py --count   # inversion total
    python tooling/architecture/js_registry_layering.py --json    # machine-readable

Comments are stripped with the shared ``js_imports`` parser before matching, so
a ``useService`` named in a JSDoc block or a commented-out line creates no edge.

**A limit, stated rather than hidden.** Only literal service keys resolve; a
service reached by a computed key is not seen. The pinned total is a floor.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root
from js_imports import strip_comments  # sys.path set by conftest.py

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_registry_layering")
WEB_SRC = ROOT / "addons" / "web" / "static" / "src"

# Must match js_layer_check.CONTRACTS; test_js_registry_layering enforces it.
LAYER_ORDER: tuple[str, ...] = (
    "core",
    "ui",
    "components",
    "model",
    "fields",
    "search",
    "views",
    "webclient",
)
RANK = {name: i for i, name in enumerate(LAYER_ORDER)}

PRODUCER_RE = re.compile(
    r'registry\s*\.\s*category\(\s*"services"\s*\)\s*\.\s*add\(\s*"([^"]+)"'
)
CONSUMER_RES = (
    re.compile(r'useService\(\s*"([^"]+)"\s*\)'),
    re.compile(r"\benv\s*\.\s*services\s*\.\s*([A-Za-z_$][\w$]*)"),
    re.compile(r'\bservices\s*\[\s*"([^"]+)"\s*\]'),
)

# Contract B — any category, but only KEYED lookups. See the module docstring
# for why enumeration is excluded and naming an item is not.
CATEGORY_ADD_RE = re.compile(
    r'registry\s*\.\s*category\(\s*"([^"]+)"\s*\)\s*\.\s*add\(\s*"([^"]+)"'
)
CATEGORY_GET_RE = re.compile(
    r'registry\s*\.\s*category\(\s*"([^"]+)"\s*\)\s*\.\s*get\(\s*"([^"]+)"'
)
# `const views = registry.category("views")` … later `views.get("form")`. Eight
# of the fourteen pinned keyed inversions are only reachable through this form.
CATEGORY_BIND_RE = re.compile(
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r'registry\s*\.\s*category\(\s*"([^"]+)"\s*\)'
)
# The third form, and the one that hid an entire seam. `core/shared_components.js`
# does `export const sharedComponents = registry.category("shared_components")`;
# six `views/` modules import that symbol and call `.add("ViewButton", …)` on it,
# and eight sites in `fields/` call `.get("ViewButton")`. Neither regex above sees
# any of it: CATEGORY_ADD_RE wants the inline `registry.category("…").add(` form,
# and CATEGORY_BIND_RE only resolves a binding inside the file that made it. So a
# category exported as a symbol laundered every dependency taken through it past
# this gate — in BOTH directions, registration and lookup.
#
# That matters beyond the count: it means "route it through `sharedComponents`"
# would have read as a way to *fix* an inversion when it only hides one. The
# entries this now reports are real, and are pinned as deliberate seams below.
CATEGORY_EXPORT_BIND_RE = re.compile(
    r"export\s+const\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r'registry\s*\.\s*category\(\s*"([^"]+)"\s*\)'
)
NAMED_IMPORT_RE = re.compile(r'import\s*\{([^}]*)\}\s*from\s*"([^"]+)"')


@dataclass(frozen=True)
class Known:
    """A pinned inversion: ``module`` consumes ``service``, produced higher up.

    Drift-zero — any inversion not listed here fails immediately. ``consumer``
    and ``producer`` record the layers at pinning time so a *changed* inversion
    (same pair, different layers, i.e. a file that moved) reads as new.
    """

    module: str
    service: str
    consumer: str
    producer: str


@dataclass(frozen=True)
class KnownKeyed:
    """A pinned keyed-lookup inversion: ``module`` does ``.get("key")`` on
    ``category``, whose registrar sits in a higher layer."""

    module: str
    category: str
    key: str
    consumer: str
    producer: str


@dataclass
class Inversion:
    module: str
    service: str
    consumer_layer: str
    producer_layer: str
    producer: str
    lineno: int
    contract: str = "services"


# 7 inversions. Was 32: the `action` service accounted for 26 of them until
# `@web/core/action_port` collapsed those into the single deliberate seam below.
KNOWN_INVERSIONS: tuple[Known, ...] = (
    # The composition seam, and the point of the port: ONE named upward edge
    # instead of 26 diffuse ones. `core/action_port.js` binds the `webclient/`
    # implementation and republishes three methods at the bottom of the stack,
    # so every former consumer now depends on a `core/` contract. Retiring this
    # last entry means inverting the registration itself, which is a different
    # and much larger change than the port was.
    Known("core/action_port.js", "action", "core", "webclient"),
    # core -> ui. The four that `js_layer_check` cannot see at all: written as
    # imports each fails `core-below-ui-components`, which today reports ok.
    Known("core/utils/hooks.js", "dialog", "core", "ui"),
    Known("core/utils/hooks.js", "ui", "core", "ui"),
    Known("core/utils/files.js", "notification", "core", "ui"),
    Known("core/file_upload/file_handler.js", "notification", "core", "ui"),
    Known("fields/relational/x2many_dialog.js", "view", "fields", "views"),
    Known("search/with_search/with_search.js", "view", "search", "views"),
)

# Contract B: 14 keyed lookups, measured 2026-08-03. Every one is a lower layer
# naming a `views/` implementation — `fields/` needing to embed a sub-view or
# open a form/select-create dialog. The same shape as `action` in contract A,
# and retired by the same move: a port published at the consumer's layer.
KNOWN_KEYED_INVERSIONS: tuple[KnownKeyed, ...] = (
    KnownKeyed(
        "fields/relational/x2many/x2many_field.js", "views", "kanban", "fields", "views"
    ),
    KnownKeyed(
        "fields/relational/x2many/x2many_field.js", "views", "list", "fields", "views"
    ),
    KnownKeyed(
        "fields/relational/x2many_dialog.js", "views", "form", "fields", "views"
    ),
    KnownKeyed(
        "fields/specialized/user_groups/res_user_group_ids_field.js",
        "views",
        "form",
        "fields",
        "views",
    ),
    # The record-dialog seam. Was 5 entries across 5 files in `components/` and
    # `fields/`, each naming a `views/` dialog directly; `@web/core/record_dialog_port`
    # collapsed those into the two deliberate edges below — one per dialog, in one
    # reviewable file. Same move as `action_port`, and the one this module's
    # docstring prescribes. Retiring these last two means inverting the
    # registration itself, which is a different and much larger change.
    KnownKeyed(
        "core/record_dialog_port.js", "dialogs", "select_create", "core", "views"
    ),
    KnownKeyed("core/record_dialog_port.js", "dialogs", "form_view", "core", "views"),
    # The `shared_components` seam, revealed 2026-08-04 by CATEGORY_EXPORT_BIND_RE.
    # These 8 are NOT new debt and NOT a regression: they are edges this gate could
    # not see until it learned to follow a category exported as a symbol. Pinning
    # them records what was always true.
    #
    # `core/shared_components.js` calls itself a "late-binding seam between
    # @web/views and @web/fields, which cannot import each other directly", and
    # that is a fair description of the intent. It is worth being precise about
    # what it buys: it removes the *import* edge, not the dependency. `x2many_dialog`
    # naming `loadSubViews` is bound to `views/form/form_utils` in everything but
    # syntax — which is exactly the rule this module states for `.get("select_create")`.
    # Retiring them means giving `fields/` its own copy of these helpers or moving
    # them below both layers; neither is a port, so neither belongs to P-1.
    KnownKeyed(
        "fields/relational/x2many/x2many_field.js",
        "shared_components",
        "ViewButton",
        "fields",
        "views",
    ),
    KnownKeyed(
        "fields/relational/x2many/x2many_field.js",
        "shared_components",
        "computeViewClassName",
        "fields",
        "views",
    ),
    KnownKeyed(
        "fields/relational/x2many_dialog.js",
        "shared_components",
        "ViewButton",
        "fields",
        "views",
    ),
    KnownKeyed(
        "fields/relational/x2many_dialog.js",
        "shared_components",
        "computeViewClassName",
        "fields",
        "views",
    ),
    KnownKeyed(
        "fields/relational/x2many_dialog.js",
        "shared_components",
        "useViewButtons",
        "fields",
        "views",
    ),
    KnownKeyed(
        "fields/relational/x2many_dialog.js",
        "shared_components",
        "useFormViewInDialog",
        "fields",
        "views",
    ),
    KnownKeyed(
        "fields/relational/x2many_dialog.js",
        "shared_components",
        "executeButtonCallback",
        "fields",
        "views",
    ),
    KnownKeyed(
        "fields/relational/x2many_dialog.js",
        "shared_components",
        "loadSubViews",
        "fields",
        "views",
    ),
)


def layer_of(rel: str) -> str | None:
    """The governed layer a ``static/src``-relative path belongs to, or None."""
    top = rel.split("/", maxsplit=1)[0]
    return top if top in RANK else None


def iter_source_files() -> list[Path]:
    if not WEB_SRC.is_dir():
        return []
    return [f for f in sorted(WEB_SRC.rglob("*.js")) if "__pycache__" not in f.parts]


def resolve(files: list[Path]) -> tuple[dict[str, str], list[tuple[str, str, int]]]:
    """Return ``(service -> producer path, [(consumer path, service, line)])``."""
    producers: dict[str, str] = {}
    consumers: list[tuple[str, str, int]] = []
    for path in files:
        rel = path.relative_to(WEB_SRC).as_posix()
        try:
            src = strip_comments(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError) as exc:  # pragma: no cover
            print(f"warning: could not read {path}: {exc}", file=sys.stderr)
            continue
        for m in PRODUCER_RE.finditer(src):
            producers[m.group(1)] = rel
        for pattern in CONSUMER_RES:
            consumers.extend(
                (rel, m.group(1), src[: m.start()].count("\n") + 1)
                for m in pattern.finditer(src)
            )
    return producers, consumers


def spec_to_rel(specifier: str) -> str | None:
    """``@web/core/shared_components`` -> ``core/shared_components.js``."""
    if not specifier.startswith("@web/"):
        return None
    return specifier[len("@web/") :] + ".js"


def imported_category_aliases(
    src: str, exported: dict[tuple[str, str], str]
) -> dict[str, str]:
    """Local name -> category, for category bindings imported from another file.

    ``exported`` maps ``(module rel path, exported name)`` to its category.
    Handles ``import { sharedComponents as shared } from "@web/core/…"``.
    """
    aliases: dict[str, str] = {}
    for m in NAMED_IMPORT_RE.finditer(src):
        source = spec_to_rel(m.group(2))
        if source is None:
            continue
        for clause in m.group(1).split(","):
            parts = clause.split()
            if not parts:
                continue
            name, local = parts[0], parts[-1]
            category = exported.get((source, name))
            if category is not None:
                aliases[local] = category
    return aliases


def resolve_keyed(
    files: list[Path],
) -> tuple[dict[tuple[str, str], str], list[tuple[str, str, str, int]]]:
    """Return ``({(category, key): registrar}, [(module, category, key, line)])``."""
    registrars: dict[tuple[str, str], str] = {}
    lookups: list[tuple[str, str, str, int]] = []
    texts: list[tuple[str, str]] = []
    exported: dict[tuple[str, str], str] = {}
    for path in files:
        rel = path.relative_to(WEB_SRC).as_posix()
        try:
            src = strip_comments(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError, OSError:  # pragma: no cover
            continue
        texts.append((rel, src))
        for m in CATEGORY_ADD_RE.finditer(src):
            registrars[(m.group(1), m.group(2))] = rel
        for m in CATEGORY_EXPORT_BIND_RE.finditer(src):
            exported[(rel, m.group(1))] = m.group(2)

    # Registrations through an imported binding must all be resolved before any
    # lookup is classified, or a `.get` would resolve against a half-built map
    # and read as "nobody registered this key".
    for rel, src in texts:
        for local, category in imported_category_aliases(src, exported).items():
            for m in re.finditer(re.escape(local) + r'\s*\.\s*add\(\s*"([^"]+)"', src):
                registrars[(category, m.group(1))] = rel

    for rel, src in texts:
        lookups.extend(
            (rel, m.group(1), m.group(2), src[: m.start()].count("\n") + 1)
            for m in CATEGORY_GET_RE.finditer(src)
        )
        local_bindings = {
            bind.group(1): bind.group(2) for bind in CATEGORY_BIND_RE.finditer(src)
        }
        for local, category in (
            local_bindings | imported_category_aliases(src, exported)
        ).items():
            lookups.extend(
                (rel, category, m.group(1), src[: m.start()].count("\n") + 1)
                for m in re.finditer(
                    re.escape(local) + r'\s*\.\s*get\(\s*"([^"]+)"', src
                )
            )
    return registrars, lookups


def check(files: list[Path] | None = None) -> tuple[list[Inversion], list[Inversion]]:
    """Return ``(new_inversions, known_inversions)`` across both contracts."""
    files = files if files is not None else iter_source_files()
    new: list[Inversion] = []
    known: list[Inversion] = []

    producers, consumers = resolve(files)
    pinned = {(k.module, k.service, k.consumer, k.producer) for k in KNOWN_INVERSIONS}
    seen: set[tuple[str, str]] = set()
    for rel, service, lineno in consumers:
        producer = producers.get(service)
        if producer is None or producer == rel or (rel, service) in seen:
            continue
        c_layer, p_layer = layer_of(rel), layer_of(producer)
        if c_layer is None or p_layer is None or RANK[c_layer] >= RANK[p_layer]:
            continue
        seen.add((rel, service))
        inv = Inversion(rel, service, c_layer, p_layer, producer, lineno, "services")
        bucket = known if (rel, service, c_layer, p_layer) in pinned else new
        bucket.append(inv)

    registrars, lookups = resolve_keyed(files)
    pinned_keyed = {
        (k.module, k.category, k.key, k.consumer, k.producer)
        for k in KNOWN_KEYED_INVERSIONS
    }
    seen_keyed: set[tuple[str, str, str]] = set()
    for rel, category, key, lineno in lookups:
        registrar = registrars.get((category, key))
        if registrar is None or registrar == rel or (rel, category, key) in seen_keyed:
            continue
        c_layer, p_layer = layer_of(rel), layer_of(registrar)
        if c_layer is None or p_layer is None or RANK[c_layer] >= RANK[p_layer]:
            continue
        seen_keyed.add((rel, category, key))
        inv = Inversion(
            rel,
            f"{category}:{key}",
            c_layer,
            p_layer,
            registrar,
            lineno,
            "keyed-lookup",
        )
        bucket = (
            known if (rel, category, key, c_layer, p_layer) in pinned_keyed else new
        )
        bucket.append(inv)
    return new, known


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any NEW inversion"
    )
    parser.add_argument("--count", action="store_true", help="print the total only")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    files = iter_source_files()
    if not files:
        parser.error(f"no JS sources under {WEB_SRC} — the scan reached nothing")

    new, known = check(files)

    if args.count:
        print(len(new) + len(known))
    elif args.json:
        print(
            json.dumps(
                {
                    "new": [i.__dict__ for i in new],
                    "known": [i.__dict__ for i in known],
                    "files_scanned": len(files),
                },
                indent=2,
            )
        )
    else:
        print("JS registry-mediated layering check (the half imports don't show)")
        print("=" * 68)
        by_service: dict[str, int] = {}
        for inv in new + known:
            by_service[inv.service] = by_service.get(inv.service, 0) + 1
        for service, n in sorted(by_service.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>3}  {service}")
        print("-" * 68)
        if new:
            print(f"\n{len(new)} NEW inversion(s) — these fail the gate:\n")
            for inv in new:
                print(f"  {inv.module}:{inv.lineno}")
                print(
                    f"      {inv.consumer_layer} consumes '{inv.service}' "
                    f"produced by {inv.producer_layer} ({inv.producer})"
                )
        else:
            print("\nNo new registry layer inversions. ✓")
        if known:
            print(f"\n{len(known)} pinned inversion(s) (tracked debt):\n")
            for inv in known:
                print(
                    f"  {inv.module}:{inv.lineno}  {inv.consumer_layer} -> "
                    f"'{inv.service}' ({inv.producer_layer})"
                )
        print(f"\nFiles scanned: {len(files)}")
        print(f"New: {len(new)}   Pinned: {len(known)}")

    if args.check and new:
        print(f"\nFAILED: {len(new)} new registry layer inversion(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
