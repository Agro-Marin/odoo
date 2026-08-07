#!/usr/bin/env python3
"""generate_model_types.py — emit TypeScript .d.ts from Odoo fields_get.

Produces one ``<model_name>.d.ts`` per Odoo model under
``addons/odoo/addons/web/static/src/@types/models/<module>/`` so that
``RelationalRecord<"sale.order">.data.partner_id`` resolves to
``Many2one<"res.partner">`` instead of ``any``.  Pairs with the
existing typecheck CI gate (``tooling/typecheck/scope_gate.py``):
the generated types resolve a large fraction of the baseline's
``TS18047`` / ``TS18048`` ("possibly null") errors that come from
unknown ``record.data`` shape.

USAGE
-----

All paths below are relative to the odoo checkout root (the directory
holding ``odoo-bin``); nothing here assumes a particular machine.

Via the wrapper (preferred — discovers the venv and config itself):

    DB=<db> ./tooling/codegen/regen_model_types.sh sale,sale_management,stock

From a running Odoo shell (fields_get reflects the live inheritance chain):

    ./odoo-bin shell -c <config> -d <db> <<'PY'
    import sys; sys.path.insert(0, "tooling/codegen")
    from generate_model_types import generate
    generate(env, modules=["sale", "sale_management", "stock"])
    PY

Standalone (bootstraps Odoo internally — slower but self-contained):

    python tooling/codegen/generate_model_types.py \\
        --config <config> --db <db> \\
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

# See generate_service_types.py: anchored on the checkout root, not the workspace.
ODOO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="generate_model_types")
DEFAULT_OUTPUT_DIR = ODOO_ROOT / "addons/web/static/src/@types/models"

_SELECTION_KEY_CAP = 32


def _rel(path: Path) -> Path:
    """Path relative to the checkout root, so output never leaks a machine layout."""
    try:
        return path.resolve().relative_to(ODOO_ROOT)
    except ValueError:
        return path


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
            return "string"
        keys = [k for k, _ in sel if isinstance(k, str)]
        if not keys:
            return "string"
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
        return "number | false"

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
        f"``tooling/codegen/generate_model_types.py "
        f"--modules={module}``.\n"
        f" */\n"
    )

    lines.append('declare module "@web/@types/models/_runtime" {\n')
    if used_brands:
        lines.append(_emit_imports(used_brands))

    lines.append(f"    interface {iface} {{\n")

    for fname in sorted(fields):
        field = fields[fname]
        if fname.startswith("x_"):
            continue
        ts_type = _render_field_type(field)
        marker = "" if _is_required(field) else "?"
        lines.append(f"        {fname}{marker}: {ts_type};\n")

    lines.append("    }\n")

    lines.append("\n    interface Models {\n")
    lines.append(f'        "{model_name}": {iface};\n')
    lines.append("    }\n")

    lines.append("}\n")

    lines.append(f'\nexport type {{ {iface} }} from "@web/@types/models/_runtime";\n')

    return "".join(lines)


def generate(
    env: Any,
    *,
    modules: Iterable[str] | None = None,
    models: Iterable[str] | None = None,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    quiet: bool = False,
    check: bool = False,
) -> dict[str, Path]:
    """Emit .d.ts files for the given models.

    :param env: Odoo Environment (from ``odoo-bin shell`` or bootstrap).
    :param modules: technical names of modules to emit (default: all
        installed). Mutually exclusive with ``models``.
    :param models: explicit model names to emit (e.g. ``["sale.order"]``).
        Mutually exclusive with ``modules``.
    :param output_dir: where to write ``<module>/<model>.d.ts``.
    :param quiet: suppress per-file logging.
    :param check: do not write; return only the files that disagree with the
        registry — missing, stale, or **orphaned** (committed for a model that
        no longer exists, keyed as ``"(orphan) <path>"``). The sibling
        ``generate_service_types.py`` has had a ``--check`` mode wired into
        ``service_types.yml`` since it was written, so a drifted services.d.ts
        is caught; model types had no equivalent and could drift silently for as
        long as nobody happened to regenerate them.
    :return: mapping of model name → output Path written (or, under ``check``,
        → the path that disagrees with what the registry says it should hold).
    """
    if modules and models:
        raise ValueError("Pass either modules= or models=, not both.")

    output_dir = Path(output_dir)
    if not check:
        output_dir.mkdir(parents=True, exist_ok=True)

    targets: list[tuple[str, str]] = []
    if models:
        for model_name in models:
            if model_name not in env.registry:
                if not quiet:
                    print(f"  skip (not in registry): {model_name}")
                continue
            ModelCls = env[model_name]
            module = getattr(ModelCls, "_original_module", None) or "base"
            targets.append((module, model_name))
    else:
        installed = {
            m.name
            for m in env["ir.module.module"].search([("state", "=", "installed")])
        }
        wanted = set(modules) if modules else installed
        if modules:
            # A typo used to emit nothing and exit 0 — `--modules sales` looked
            # exactly like a module that legitimately declares no models.
            unknown = sorted(wanted - installed)
            if unknown:
                raise ValueError(
                    f"not installed in this database: {', '.join(unknown)}. "
                    f"Nothing would be generated for them, and a silent empty "
                    f"run is indistinguishable from success."
                )
        for model_name in env.registry:
            ModelCls = env[model_name]
            module = getattr(ModelCls, "_original_module", None) or "base"
            if module in wanted:
                targets.append((module, model_name))

    written: dict[str, Path] = {}
    # `_file_name` maps "." to "_", so two model names can collapse onto one
    # file: `res.partner.category` and `res.partner_category` both become
    # `res_partner_category.d.ts`. Whichever is emitted second silently wins and
    # the other model's types simply vanish. Detect it rather than lose a file.
    claimed: dict[Path, str] = {}
    for module, model_name in sorted(targets):
        ir_model = env["ir.model"].search([("model", "=", model_name)], limit=1)
        if not ir_model:
            continue
        if ir_model.transient or (
            ir_model.modules == "base"
            and (getattr(env[model_name], "_abstract", False))
        ):
            continue

        fields = env[model_name].fields_get()
        content = _model_to_dts(model_name, fields, module)

        target_dir = output_dir / module
        target_path = target_dir / _file_name(model_name)

        if (clash := claimed.get(target_path)) is not None:
            raise ValueError(
                f"model name collision: {clash!r} and {model_name!r} both map to "
                f"{_rel(target_path)}. Emitting both would silently drop one; "
                f"disambiguate _file_name() before regenerating."
            )
        claimed[target_path] = model_name

        if check:
            try:
                current = target_path.read_text(encoding="utf-8")
            except OSError:
                current = None
            if current == content:
                continue
            written[model_name] = target_path
            if not quiet:
                state = "missing" if current is None else "stale"
                print(f"  {state}: {model_name:<40s} → {_rel(target_path)}")
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        written[model_name] = target_path
        if not quiet:
            print(f"  emit: {model_name:<40s} → {_rel(target_path)}")

    if check:
        # A model that is DELETED leaves its .d.ts behind, and comparing
        # registry -> disk can never see it: the loop above only visits models
        # that still exist. The orphan then keeps contributing an `interface`
        # and a `Models` entry for a model the server no longer has, and
        # `--check` reports "up to date". Every sibling gate here detects its
        # own version of this (scope_gate's `stale`, py_cycle_check's
        # `stale_pins`, package_index_check's `phantom`); this one did not.
        #
        # Scoped to the module directories actually targeted: with `--modules
        # sale`, every OTHER module's committed file is untouched, not orphaned.
        for module in sorted({m for m, _ in targets}):
            module_dir = output_dir / module
            if not module_dir.is_dir():
                continue
            expected = {p for p in claimed if p.parent == module_dir}
            for path in sorted(module_dir.glob("*.d.ts")):
                if path in expected:
                    continue
                written[f"(orphan) {_rel(path)}"] = path
                if not quiet:
                    print(f"  orphan: {_rel(path)} — no model claims this file")

    if not quiet:
        if check:
            print(
                f"\n{len(written)} .d.ts file(s) out of date under {output_dir}"
                if written
                else f"\nAll .d.ts files under {output_dir} are up to date."
            )
        else:
            print(f"\nGenerated {len(written)} .d.ts files under {output_dir}")
    return written


def _bootstrap_odoo(config_path: str, db: str) -> Any:
    """Initialise Odoo and return an Environment for ``db``."""
    sys.path.insert(0, str(ODOO_ROOT))
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
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "CI mode: exit non-zero if any committed .d.ts disagrees with the "
            "registry. Does not write. Mirrors generate_service_types.py."
        ),
    )
    args = parser.parse_args()

    env = _bootstrap_odoo(args.config, args.db)
    try:
        kwargs: dict[str, Any] = {
            "output_dir": args.output_dir,
            "quiet": args.quiet,
            "check": args.check,
        }
        if args.modules:
            kwargs["modules"] = [m.strip() for m in args.modules.split(",")]
        if args.models:
            kwargs["models"] = [m.strip() for m in args.models.split(",")]
        try:
            stale = generate(env, **kwargs)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    finally:
        env.cr.close()
    if args.check and stale:
        print(
            f"✗ {len(stale)} model type file(s) are out of date. "
            f"Regenerate with ./tooling/codegen/regen_model_types.sh",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
