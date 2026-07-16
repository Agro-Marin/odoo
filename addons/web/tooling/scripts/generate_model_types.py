#!/usr/bin/env python3
"""generate_model_types.py — emit TypeScript .d.ts from Odoo fields_get.

Produces one ``<model_name>.d.ts`` per Odoo model under
``addons/odoo/addons/web/static/src/@types/models/<module>/`` so that
``RelationalRecord<"sale.order">.data.partner_id`` resolves to
``Many2one<"res.partner">`` instead of ``any``.  Pairs with the
existing typecheck CI gate (``tooling/scripts/typecheck_gate.mjs``):
the generated types resolve a large fraction of the baseline's
``TS18047`` / ``TS18048`` ("possibly null") errors that come from
unknown ``record.data`` shape.

USAGE
-----

From a running Odoo shell (preferred — fields_get reflects the live
inheritance chain):

    cd /home/marin/Odoo
    ./addons/odoo/odoo-bin shell -c conf/odoo.conf -d $DB <<'PY'
    from addons.core.addons.web.tooling.scripts.generate_model_types import generate
    generate(env, modules=["sale", "sale_management", "stock"])
    PY

Standalone (bootstraps Odoo internally — slower but self-contained):

    python tooling/scripts/generate_model_types.py \\
        --config conf/odoo.conf --db marin190 \\
        --modules sale,sale_management,stock

Output goes to ``addons/odoo/addons/web/static/src/@types/models/`` by
default; pass ``--output-dir`` to override.

DESIGN CHOICES
--------------

- **One file per model, filed under its defining module**: each model
  gets exactly one ``.d.ts``, written to
  ``<output_dir>/<original_module>/<model>.d.ts`` where
  ``original_module`` is whichever module first declared the model
  (``_original_module`` — set once, at class creation; ``_inherit``
  extensions don't get their own entry).  Fields added later by an
  extending module (e.g. ``sale_management`` on ``sale.order``) are
  folded into that same file on the next regen, since ``fields_get()``
  already returns the full merged field set — there is no per-module
  overlay file.  Declaration merging is used across files at the
  ``Models`` registry level (each file contributes one entry to the
  global ``Models`` map), not to split one model's fields across
  several files.

- **No ``x_*`` custom fields**: those are per-deployment, not per-codebase.
  Including them would couple the type repo to a specific database.

- **Server fields as source of truth**: the script reads ``fields_get``
  via a live registry rather than parsing Python AST.  Computed fields,
  related fields, and inheritance overlays only resolve correctly after
  the registry is built.

- **Field optionality**: fields with ``required=True`` and no default
  are emitted as required (``foo: T``); everything else is optional
  (``foo?: T``).  This is conservative — a field can be ``required=True``
  on the server but not yet set on a freshly-created in-memory record.
  Worth revisiting once we observe how often the tighter form bites.

- **Selection unions**: ``selection`` fields emit a string-literal union
  of their keys (``"draft" | "sent" | "sale"``).  ``fields_get()``
  already resolves callable/dynamic selections to a concrete list
  before this script sees them, so the ``string`` fallback below is
  for an empty/malformed selection or one over
  ``_SELECTION_KEY_CAP`` keys — not for "is it dynamic."

- **No regeneration order dependency**: each output file is independent
  and can be regenerated alone.  The codegen never reads back its own
  output.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# Path math: /home/marin/Odoo/addons/odoo/addons/web/tooling/scripts/<this>
#   parents[0] = scripts/, [1] = tooling/, [2] = web/,
#   parents[3] = addons/ (inner), [4] = core/, [5] = addons/ (outer),
#   parents[6] = Odoo/        ← the workspace root.
REPO_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "addons/odoo/addons/web/static/src/@types/models"

# Selection literal-union cap — past this, fall back to ``string``.
# Calibrated against ``res.partner.tz`` (~400 IANA zones, was producing
# ~10 KB unions on a single line).  Common state-machine selections
# (draft/sent/sale/done style) stay well under the cap and keep their
# literal types.
_SELECTION_KEY_CAP = 32

# Map ttype → emitter producing a TS type expression for the field's value.
# Emitters take the raw fields_get entry and return a string.
SCALAR_TYPE_MAP = {
    "char": "string",
    "text": "string",
    "html": "string",
    "integer": "number",
    "float": "number",
    "monetary": "number",
    "boolean": "boolean",
    "date": "string",
    "datetime": "string",
    "binary": "string | false",
    "image": "string | false",
    "json": "unknown",
    "properties": "Properties",
    "properties_definition": "unknown[]",
}


def _interface_name(model_name: str) -> str:
    """Convert ``"sale.order.line"`` → ``"SaleOrderLine"`` (PascalCase)."""
    return "".join(part.capitalize() for part in model_name.split("."))


def _module_name_safe(module: str) -> str:
    """Convert ``"sale_management"`` → ``"sale_management"`` (filesystem-safe).

    Currently a no-op since module names already follow snake_case, but
    centralized so future renames (hyphen handling, etc.) update here.
    """
    return module


def _file_name(model_name: str) -> str:
    """Convert ``"sale.order.line"`` → ``"sale_order_line.d.ts"``."""
    return model_name.replace(".", "_") + ".d.ts"


def _render_field_type(field: dict[str, Any]) -> str:
    """Render a TypeScript type expression for one fields_get entry."""
    ttype = field["type"]

    if ttype in SCALAR_TYPE_MAP:
        return SCALAR_TYPE_MAP[ttype]

    if ttype == "selection":
        sel = field.get("selection") or []
        if not sel or not isinstance(sel, list):
            # Defensive fallback only: fields_get() always resolves the
            # selection (including callable/dynamic definitions) to a
            # list of pairs, so this guards an empty/malformed value,
            # not "the selection was a lambda."
            return "string"
        keys = [k for k, _ in sel if isinstance(k, str)]
        if not keys:
            return "string"
        # Large selections (e.g. ``res.partner.tz`` with ~400 IANA zones)
        # produce 10 KB+ unions that hurt IDE performance and are
        # unreadable.  TS compiles them fine, but the cost/benefit
        # inverts past ~32 options — at that point the field is
        # de-facto an open enum and ``string`` carries the same value.
        # Threshold chosen so common selections (state machines,
        # category enums) keep their literal types while pathological
        # ones don't bloat output.
        if len(keys) > _SELECTION_KEY_CAP:
            return "string"
        return " | ".join(f'"{k}"' for k in keys)

    if ttype == "many2one":
        relation = field.get("relation", "")
        return f'Many2one<"{relation}">' if relation else "Many2one<string>"

    if ttype in ("one2many", "many2many"):
        relation = field.get("relation", "")
        ts_brand = "One2many" if ttype == "one2many" else "Many2many"
        return f'{ts_brand}<"{relation}">' if relation else f"{ts_brand}<string>"

    if ttype == "reference":
        return "Reference"

    if ttype == "many2one_reference":
        # Stored as integer; the target model is recorded in a sibling field.
        return "number | false"

    # Unknown type — emit ``unknown`` rather than crashing.  Codegen
    # tolerates new field types; the typecheck baseline catches surprises.
    return "unknown"


def _is_required(field: dict[str, Any]) -> bool:
    """True if the field is server-required and has no default.

    Conservative — required fields can still be unset on freshly-created
    in-memory records (before save).  We treat them as required only if
    the server contract is required AND there is no ``default`` (which
    would mean "auto-filled, never observed unset by client code").
    """
    return bool(field.get("required")) and not field.get("default")


def _emit_imports(used_brands: set[str]) -> str:
    """Emit the ``import type`` line for whichever brands the file uses."""
    if not used_brands:
        return ""
    sorted_brands = sorted(used_brands)
    items = ", ".join(sorted_brands)
    return f'    import type {{ {items} }} from "@web/@types/models/_runtime";\n\n'


def _scan_used_brands(fields: dict[str, dict]) -> set[str]:
    """Return the set of brand names this model's fields will reference."""
    used: set[str] = set()
    for field in fields.values():
        ttype = field["type"]
        if ttype == "many2one":
            used.add("Many2one")
        elif ttype == "one2many":
            used.add("One2many")
        elif ttype == "many2many":
            used.add("Many2many")
        elif ttype == "reference":
            used.add("Reference")
        elif ttype == "properties":
            used.add("Properties")
    return used


def _model_to_dts(model_name: str, fields: dict[str, dict], module: str) -> str:
    """Render the full .d.ts content for one model contribution."""
    iface = _interface_name(model_name)
    used_brands = _scan_used_brands(fields)
    lines: list[str] = []

    lines.append(
        f"/**\n"
        f" * GENERATED — do not edit.\n"
        f" * Source: ``{model_name}.fields_get()`` "
        f"(module ``{module}``).\n"
        f" * Re-run: "
        f"``tooling/scripts/generate_model_types.py "
        f"--modules={module}``.\n"
        f" */\n"
    )

    lines.append('declare module "@web/@types/models/_runtime" {\n')
    if used_brands:
        lines.append(_emit_imports(used_brands))

    lines.append(f"    interface {iface} {{\n")

    for fname in sorted(fields):
        field = fields[fname]
        # Skip user-custom fields (per-deployment, not per-codebase).
        if fname.startswith("x_"):
            continue
        ts_type = _render_field_type(field)
        marker = "" if _is_required(field) else "?"
        # Server help/string isn't carried into the type — too noisy and
        # rots faster than the field shape.
        lines.append(f"        {fname}{marker}: {ts_type};\n")

    lines.append("    }\n")

    # Register the interface into the global ``Models`` map.  Module
    # boundaries are preserved via declaration merging — each module's
    # output file declares the same interface; TS unions them.
    lines.append("\n    interface Models {\n")
    lines.append(f'        "{model_name}": {iface};\n')
    lines.append("    }\n")

    lines.append("}\n")

    # The export keeps the file picked up by ``import type`` paths,
    # though declaration merging makes the explicit re-export
    # unnecessary.  Provided for IDE go-to-definition navigation.
    lines.append(f'\nexport type {{ {iface} }} from "@web/@types/models/_runtime";\n')

    return "".join(lines)


def generate(
    env: Any,
    *,
    modules: Iterable[str] | None = None,
    models: Iterable[str] | None = None,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    quiet: bool = False,
) -> dict[str, Path]:
    """Emit .d.ts files for the given models.

    :param env: Odoo Environment (from ``odoo-bin shell`` or bootstrap).
    :param modules: technical names of modules to emit (default: all
        installed). Mutually exclusive with ``models``.
    :param models: explicit model names to emit (e.g. ``["sale.order"]``).
        Mutually exclusive with ``modules``.
    :param output_dir: where to write ``<module>/<model>.d.ts``.
    :param quiet: suppress per-file logging.
    :return: mapping of model name → output Path written.
    """
    if modules and models:
        raise ValueError("Pass either modules= or models=, not both.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect (module, model_name) pairs to emit.
    targets: list[tuple[str, str]] = []
    if models:
        for model_name in models:
            if model_name not in env.registry:
                if not quiet:
                    print(f"  skip (not in registry): {model_name}")
                continue
            # Attribute to the module that defined the model class.
            ModelCls = env[model_name]
            module = getattr(ModelCls, "_original_module", None) or "base"
            targets.append((module, model_name))
    else:
        installed = env["ir.module.module"].search([("state", "=", "installed")])
        wanted = set(modules) if modules else {m.name for m in installed}
        for model_name in env.registry:
            ModelCls = env[model_name]
            module = getattr(ModelCls, "_original_module", None) or "base"
            if module in wanted:
                targets.append((module, model_name))

    written: dict[str, Path] = {}
    for module, model_name in sorted(targets):
        ir_model = env["ir.model"].search([("model", "=", model_name)], limit=1)
        if not ir_model:
            continue
        # Transient models are always skipped (no data-layer records to
        # type).  Abstract models are skipped only when ``modules``
        # (comma-joined list of contributing modules) is exactly
        # ``"base"`` — due to operator precedence this is
        # ``transient or (modules == "base" and abstract)``, so an
        # abstract model extended by any non-base module is NOT
        # skipped here.  Worth revisiting if wizards want types.
        if ir_model.transient or (
            ir_model.modules == "base"
            and (getattr(env[model_name], "_abstract", False))
        ):
            continue

        fields = env[model_name].fields_get()
        content = _model_to_dts(model_name, fields, module)

        target_dir = output_dir / _module_name_safe(module)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / _file_name(model_name)
        target_path.write_text(content)
        written[model_name] = target_path
        if not quiet:
            try:
                rel = target_path.relative_to(REPO_ROOT)
            except ValueError:
                # Output dir is outside the repo (e.g. /tmp during smoke
                # tests).  Fall back to the absolute path.
                rel = target_path
            print(f"  emit: {model_name:<40s} → {rel}")

    if not quiet:
        print(f"\nGenerated {len(written)} .d.ts files under {output_dir}")
    return written


# ───────────────────────────────────────────────────────────────────────
# Standalone bootstrap — used when invoked as ``python script.py …``.
# In an ``odoo-bin shell`` session, prefer ``from … import generate;
# generate(env, …)`` directly.
# ───────────────────────────────────────────────────────────────────────


def _bootstrap_odoo(config_path: str, db: str) -> Any:
    """Initialise Odoo and return an Environment for ``db``."""
    # Lazy import — only needed in standalone mode.
    sys.path.insert(0, str(REPO_ROOT / "addons/odoo"))
    import odoo  # type: ignore[import-not-found]
    from odoo.tools import config  # type: ignore[import-not-found]

    config.parse_config(["-c", config_path])
    odoo.cli.server.report_configuration()
    registry = odoo.modules.registry.Registry(db)
    cr = registry.cursor()
    return odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate TS .d.ts files from Odoo fields_get."
    )
    parser.add_argument("--config", required=True, help="Path to odoo.conf")
    parser.add_argument("--db", required=True, help="Database name")
    parser.add_argument(
        "--modules",
        help="Comma-separated module names (default: all installed).",
    )
    parser.add_argument(
        "--models",
        help="Comma-separated model names (e.g. sale.order,res.partner).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    env = _bootstrap_odoo(args.config, args.db)
    try:
        kwargs: dict[str, Any] = {
            "output_dir": args.output_dir,
            "quiet": args.quiet,
        }
        if args.modules:
            kwargs["modules"] = [m.strip() for m in args.modules.split(",")]
        if args.models:
            kwargs["models"] = [m.strip() for m in args.models.split(",")]
        generate(env, **kwargs)
    finally:
        env.cr.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
