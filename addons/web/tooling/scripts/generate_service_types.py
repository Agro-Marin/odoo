#!/usr/bin/env python3
"""generate_service_types.py — emit ``@types/services.d.ts`` from JS source.

Produces ``addons/odoo/addons/web/static/src/@types/services.d.ts`` from
the actual ``registry.category("services").add(...)`` call sites under
``addons/odoo/addons/web/static/src/``.  The hand-maintained file drifts
silently when a service is added or moved (one observed drift on
2026-05-10: ``httpService`` was imported from ``@web/core/network/http_service``
but the registration lives in ``@web/services/http_service``).  Pairs
with ``typecheck_gate.mjs``: a typed service registry resolves
``useService("orm")`` to ``ORM`` instead of ``any``, shrinking the
TS18047/TS18048 baseline.

USAGE
-----

Regenerate the file in place::

    cd /home/marin/Odoo
    python addons/odoo/addons/web/tooling/scripts/generate_service_types.py

Convenience wrapper (matches ``regen_model_types.sh``)::

    ./addons/odoo/addons/web/tooling/scripts/regen_service_types.sh

CI freshness check (paired with the existing typecheck_gate pattern)::

    python addons/odoo/addons/web/tooling/scripts/generate_service_types.py --check
    # exits non-zero if the committed file disagrees with the regenerated one

DESIGN CHOICES
--------------

- **Static parsing, not runtime introspection**: services live in JS
  source; there is no Python-side service registry to introspect.  The
  registration grammar is highly regular (one of two
  ``registry.category("services").add(...)`` patterns), so a regex
  parser is robust enough.  Trade-off: anonymous inline-object
  registrations (``registry.category("services").add("name", { start(){} })``)
  cannot be typed — they have no exported symbol to import — and are
  silently skipped.  None of the in-tree web services use that pattern;
  the few outside of web (``stock_warehouse``, ``mass_mailing.themes``,
  ``clear_caches_on_approval_rules_change``) are out of scope for v1.

- **web module only for v1**: matches the current ``services.d.ts``
  scope.  Other addons (mail, point_of_sale, voip, web_studio, ...)
  register 130+ services that are not currently typed.  Adding them is
  a follow-up — each addon should own its own ``services.d.ts``
  contribution via TS declaration merging, mirroring the per-module
  model types already produced by ``generate_model_types.py``.

- **Tests excluded**: registrations under ``/tests/`` are mocks for
  test isolation (``bus/static/tests/multi_tab_*.test.js``), not
  production services.  Including them would surface mock factories in
  IDE autocomplete for application code.

- **Directory-derived categories**: imports are grouped by top-level
  directory (``core/``, ``public/``, ``services/``, ``ui/``, ``views/``,
  ``webclient/``, ``fields/``, ``components/``).  Mirrors the layout of
  the previous hand-maintained file so the regenerate diff is small
  and reviewable on first roll-out.

- **No regeneration order dependency**: the script reads JS source and
  emits TypeScript; it never reads back its own output.  Safe to delete
  ``services.d.ts`` and regenerate from scratch.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Path math: /home/marin/Odoo/addons/odoo/addons/web/tooling/scripts/<this>
#   parents[0] = scripts/, [1] = tooling/, [2] = web/,
#   parents[3] = addons/ (inner), [4] = core/, [5] = addons/ (outer),
#   parents[6] = Odoo/        ← the workspace root.
REPO_ROOT = Path(__file__).resolve().parents[6]
WEB_SRC_ROOT = REPO_ROOT / "addons/odoo/addons/web/static/src"
DEFAULT_OUTPUT = WEB_SRC_ROOT / "@types/services.d.ts"

# Registration grammar — three concrete forms occur in the tree:
#
#   1. Direct chain (most common):
#        registry.category("services").add("key", factoryVar);
#
#   2. Multi-line chain (chained ``add`` after ``category`` on prior line):
#        registry
#            .category("services")
#            .add("key", factoryVar);
#
#   3. Aliased registry variable (declared once per file):
#        const services = registry.category("services");
#        services.add("key", factoryVar);
#      or with a different variable name:
#        const serviceRegistry = registry.category("services");
#        serviceRegistry.add("key", factoryVar);
#
# Orthogonally, the factory argument may be wrapped in a JSDoc type cast:
#        services.add("key", /** @type {any} */ (factoryVar));
# These wrappers are stripped during a preprocessing pass
# (``_strip_jsdoc_casts``) before the registration regex runs, so the
# regex itself only has to match a bare identifier.
#
# The capture is intentionally narrow:
#   - Group 1: service key (string literal between double quotes).  Keys
#     with embedded quotes are not supported — none exist in the tree.
#   - Group 2: factory identifier.  Anonymous object literals (``{ ... }``)
#     are intentionally NOT matched — they have no exported symbol to
#     import.  They surface as a "skipped: <key>" diagnostic.
#
# ``re.DOTALL`` lets the body span newlines (multi-line ``.add(`` calls
# that put each arg on its own line).
_DIRECT_CHAIN = r'registry\s*\.\s*category\s*\(\s*"services"\s*\)'

# ``const services = registry.category("services");`` or any other
# identifier on the LHS.  Captured group becomes a per-file alias for
# the services registry.
_ALIAS_DECL_RE = re.compile(
    r"(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*" + _DIRECT_CHAIN,
)

# JSDoc cast wrapper: ``/** @type {X} */ (name)`` → ``name``.
#
# The comment body uses the standard "single block-comment" pattern
# (``[^*]*(?:\*(?!/)[^*]*)*``) instead of ``.*?``-with-DOTALL.  The
# naive non-greedy form looks correct in isolation but is unsafe across
# a whole file: at the first ``/**`` in the source, ``.*?`` is allowed
# to extend across intermediate comment closers as long as the overall
# pattern eventually succeeds, so the regex happily spans from the file
# header all the way to the first inline cast — replacing hundreds of
# lines with a single identifier and destroying the export declarations
# downstream.  The bracketed form below is anchored to one ``*/`` and
# cannot cross over.
_JSDOC_CAST_RE = re.compile(
    r"/\*\*[^*]*(?:\*(?!/)[^*]*)*\*/\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)",
)

# ``export const factoryName = …`` declaration.  ``let`` and ``var``
# are intentionally not matched — every in-tree service factory is
# declared with ``export const``; widening the match would only invite
# false positives.
_EXPORT_CONST_RE = re.compile(
    r"^\s*export\s+const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
    re.MULTILINE,
)

# Skip these path fragments.  Tests are mocks; legacy is dead-on-arrival.
_SKIP_FRAGMENTS = ("/tests/", "/legacy/")

# Top-level directories under ``static/src/`` mapped to category labels.
# Order matters: the emitted file groups imports in this order so the
# layout matches the previous hand-maintained file.
_CATEGORY_ORDER: list[tuple[str, str]] = [
    ("core", "Core infrastructure services"),
    ("public", "Public services"),
    ("services", "Domain services"),
    ("fields", "Domain services"),  # field-adjacent services
    ("components", "Domain services"),  # component-adjacent services
    ("ui", "UI overlay services"),
    ("views", "View services"),
    ("webclient", "Webclient services"),
]


@dataclass(frozen=True, order=True)
class Registration:
    """One ``registry.category("services").add(key, factory)`` call site."""

    key: str
    factory_var: str
    import_path: str
    source_file: Path
    top_level_dir: str


def _js_to_import_path(file: Path) -> str:
    """Convert a JS file path to its ``@web/...`` import specifier.

    ``addons/odoo/addons/web/static/src/services/orm_service.js``
    → ``@web/services/orm_service``
    """
    rel = file.relative_to(WEB_SRC_ROOT)
    # Strip ``.js`` and use forward slashes regardless of host OS.
    return "@web/" + rel.with_suffix("").as_posix()


def _top_level_dir(file: Path) -> str:
    """First path segment under ``static/src/`` (e.g. ``services``, ``ui``)."""
    rel = file.relative_to(WEB_SRC_ROOT)
    return rel.parts[0] if rel.parts else ""


def _find_export(text: str, var_name: str) -> bool:
    """True iff the file declares ``export const <var_name> = ...``."""
    return any(match.group(1) == var_name for match in _EXPORT_CONST_RE.finditer(text))


def _strip_jsdoc_casts(text: str) -> str:
    """Remove ``/** @type {X} */ (name)`` wrappers, leaving the bare name.

    Lets the registration regex stay simple (bare identifier as second
    argument) instead of needing to match the cast inline.  Safe because
    the result is only fed to the registration regex — we don't try to
    re-parse the modified source for any other purpose.
    """
    return _JSDOC_CAST_RE.sub(r"\1", text)


def _build_registration_re(aliases: set[str]) -> re.Pattern[str]:
    """Build the registration regex for one file's set of aliases.

    The alternation covers both the direct chain
    (``registry.category("services").add``) and any per-file alias
    variable (``X.add``).  Aliases are anchored with ``\\b`` so an
    alias named ``services`` does not also match the substring
    ``services`` inside ``serviceRegistry``.
    """
    alts = [_DIRECT_CHAIN]
    alts.extend(rf"\b{re.escape(alias)}\b" for alias in sorted(aliases))
    chain = "(?:" + "|".join(alts) + ")"
    return re.compile(
        chain
        + r"\s*\.\s*add\s*\("
        + r'\s*"([^"]+)"\s*,'  # group 1: service key
        + r"\s*([A-Za-z_][A-Za-z0-9_]*)"  # group 2: factory identifier
        + r"\s*[,)]",
        re.DOTALL,
    )


def discover(src_root: Path = WEB_SRC_ROOT) -> list[Registration]:
    """Walk web/static/src/ and collect every service registration.

    Three call patterns are recognised: direct chain, multi-line chain,
    and aliased registry variable.  JSDoc type-cast wrappers around the
    factory argument are stripped during preprocessing.  Anonymous
    inline-object registrations (no exported symbol to import) are
    skipped with a warning.

    :param src_root: filesystem root to scan (defaults to web/static/src).
    :return: registrations sorted by service key.
    """
    found: list[Registration] = []
    for js_file in sorted(src_root.rglob("*.js")):
        # Path-fragment filter — relative-to-src for portability.
        rel_str = "/" + js_file.relative_to(src_root).as_posix()
        if any(frag in rel_str for frag in _SKIP_FRAGMENTS):
            continue
        try:
            raw_text = js_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # JS source must be UTF-8 in this codebase; surface the
            # offender rather than emit a broken types file.
            print(
                f"  ✗ {js_file}: not UTF-8, skipping",
                file=sys.stderr,
            )
            continue
        text = _strip_jsdoc_casts(raw_text)
        aliases = {m.group(1) for m in _ALIAS_DECL_RE.finditer(text)}
        registration_re = _build_registration_re(aliases)
        for match in registration_re.finditer(text):
            key, factory_var = match.group(1), match.group(2)
            if not _find_export(text, factory_var):
                # Factory is registered but not declared in this file.
                # Could be: imported from elsewhere (rare for services)
                # or a typo. Surface as a warning so the operator can
                # decide; v1 skips it from the type output.
                print(
                    f"  ⚠ {js_file.name}: registers {key!r} as "
                    f"{factory_var!r} but no `export const {factory_var}` "
                    f"in same file — skipped",
                    file=sys.stderr,
                )
                continue
            found.append(
                Registration(
                    key=key,
                    factory_var=factory_var,
                    import_path=_js_to_import_path(js_file),
                    source_file=js_file,
                    top_level_dir=_top_level_dir(js_file),
                )
            )
    # Sort by key for deterministic output.
    return sorted(found)


def _quote_if_needed(key: str) -> str:
    """Wrap a service key in double quotes if it isn't a bare identifier.

    Keys with dots (``"web.frequent.emoji"``) or starting with a digit
    must be quoted; others are emitted bare.  TS accepts both, but bare
    identifiers are slightly easier to read.
    """
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return key
    return f'"{key}"'


def render(registrations: list[Registration]) -> str:
    """Render the full ``services.d.ts`` content for the given inventory.

    Layout (matches the previous hand-maintained file):

    ::

        declare module "services" {
            import { ServicesRegistryShape } from "registries";

            // Core infrastructure services
            import { fooService } from "@web/core/...";

            // Domain services
            import { barService } from "@web/services/...";

            ...

            type ExtractServiceFactory<T extends ServicesRegistryShape> =
                Awaited<ReturnType<T["start"]>>;
            export type ServiceFactories = {
                [P in keyof Services]: ExtractServiceFactory<Services[P]>;
            };

            export interface Services {
                "service.key": typeof factoryVariable;
                ...
            }
        }
    """
    out: list[str] = []
    out.append('declare module "services" {\n')
    out.append('    import { ServicesRegistryShape } from "registries";\n')

    # Group registrations by top-level directory; canonical ordering is
    # applied below by walking _CATEGORY_ORDER rather than this dict.
    by_dir: dict[str, list[Registration]] = {}
    for reg in registrations:
        by_dir.setdefault(reg.top_level_dir, []).append(reg)

    # Emit imports grouped by label, suppressing duplicate headers when
    # multiple directories map to the same label (e.g. services/, fields/,
    # components/ all → "Domain services").  The header is printed on
    # the first directory that contributes; subsequent directories in the
    # same label append silently underneath.
    last_label: str | None = None
    for dirname, label in _CATEGORY_ORDER:
        items = by_dir.get(dirname, [])
        if not items:
            continue
        if label != last_label:
            out.append("\n")
            out.append(f"    // {label}\n")
            last_label = label
        out.extend(
            f'    import {{ {reg.factory_var} }} from "{reg.import_path}";\n'
            for reg in sorted(items, key=lambda r: r.factory_var)
        )

    # Any directory not in _CATEGORY_ORDER goes under a generic
    # "Other services" header so unexpected layouts still surface.
    handled = {d for d, _ in _CATEGORY_ORDER}
    other: list[Registration] = []
    for dirname, items in by_dir.items():
        if dirname not in handled:
            other.extend(items)
    if other:
        out.append("\n    // Other services\n")
        out.extend(
            f'    import {{ {reg.factory_var} }} from "{reg.import_path}";\n'
            for reg in sorted(other, key=lambda r: r.factory_var)
        )

    out.append("\n")
    out.append(
        "    type ExtractServiceFactory<T extends ServicesRegistryShape>"
        ' = Awaited<ReturnType<T["start"]>>;\n'
    )
    out.append("    export type ServiceFactories = {\n")
    out.append("        [P in keyof Services]: ExtractServiceFactory<Services[P]>;\n")
    out.append("    };\n")
    out.append("\n")
    out.append("    export interface Services {\n")
    out.extend(
        f"        {_quote_if_needed(reg.key)}: typeof {reg.factory_var};\n"
        for reg in registrations
    )
    out.append("    }\n")
    out.append("}\n")
    return "".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate addons/odoo/addons/web/static/src/@types/services.d.ts",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Output file (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "CI mode: exit non-zero if the committed file disagrees "
            "with the regenerated one. Does not write."
        ),
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    registrations = discover()
    new_content = render(registrations)
    output_path = Path(args.output)

    if args.check:
        try:
            current = output_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(
                f"✗ {output_path} does not exist. Run without --check to generate.",
                file=sys.stderr,
            )
            return 1
        if current != new_content:
            print(
                f"✗ {output_path} is out of date.\n"
                f"  Run: python {Path(__file__).relative_to(REPO_ROOT)}",
                file=sys.stderr,
            )
            return 1
        if not args.quiet:
            print(f"✓ {output_path.relative_to(REPO_ROOT)} is up to date.")
        return 0

    output_path.write_text(new_content, encoding="utf-8")
    if not args.quiet:
        try:
            rel = output_path.relative_to(REPO_ROOT)
        except ValueError:
            # Output path is outside the repo (e.g. /tmp during smoke
            # tests). Fall back to the absolute path so the user still
            # sees where the file landed.
            rel = output_path
        print(f"✓ Wrote {len(registrations)} services to {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
