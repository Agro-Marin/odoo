"""Post-migration for web 2.0: upgrade Font Awesome 4 icon class strings to FA7 native syntax.

Affected DB fields
------------------
+------------------------------------------+-------------------+-----------------------+----------------------------+
| Table                                    | Field             | FA4 format stored     | FA7 format produced        |
+------------------------------------------+-------------------+-----------------------+----------------------------+
| ir_ui_menu                               | web_icon          | "fa-solid fa-X,color,bg"    | "fa-STYLE fa-Y,color,bg"   |
| mail_activity_type                       | icon              | "fa-X"                | "fa-STYLE fa-Y"            |
| onboarding_onboarding_step               | done_icon         | "fa-X"                | "fa-STYLE fa-Y"            |
| website_configurator_feature             | icon              | "fa-X"                | "fa-STYLE fa-Y"            |
| sign_item_type                           | icon              | "fa-X"                | "fa-STYLE fa-Y"            |
| hr_contract_salary_benefit               | icon              | "fa-solid fa-X"             | "fa-STYLE fa-Y"            |
| remote_device_category                   | icon              | "fa-X"                | "fa-STYLE fa-Y"            |
| base_credential_manager                  | icon              | "fa-X"                | "fa-STYLE fa-Y"            |
+------------------------------------------+-------------------+-----------------------+----------------------------+

Tables that may not be installed on all systems are guarded by _table_exists() checks.

The icon mapping is sourced from the canonical shims.yml file shipped with the FA7 Pro
package at: web/static/src/libs/fontawesome7/metadata/shims.yml
"""

import logging
from pathlib import Path

_logger = logging.getLogger(__name__)

# FA7 short prefix → FA7 long class prefix
_PREFIX_MAP: dict[str, str] = {
    'far': 'fa-regular',
    'fab': 'fa-brands',
    'fas': 'fa-solid',
}


# ---------------------------------------------------------------------------
# YAML shim loader (no external deps — hand-rolled for shims.yml format)
# ---------------------------------------------------------------------------

def _load_shims() -> dict[str, dict[str, str]]:
    """Parse metadata/shims.yml into a FA4-name → entry mapping.

    Each entry is a dict with optional keys:
    - 'prefix': 'far' | 'fab' | 'fas'  (default 'fas' = solid)
    - 'name': str                        (default = same as FA4 name)

    Possible shapes:
    - name only   → solid, renamed      (e.g. home → house)
    - prefix only → style changed       (e.g. eye → fa-regular fa-eye)
    - both        → style + rename      (e.g. arrow-circle-o-down → fa-regular fa-circle-down)
    - neither     → icon not in shims, i.e. solid + same name (not stored in file)
    """
    shims_path = (
        Path(__file__).parent.parent.parent
        / 'static' / 'src' / 'libs' / 'fontawesome7' / 'metadata' / 'shims.yml'
    )
    if not shims_path.exists():
        _logger.warning(
            "fa4_to_fa7 migration: shims.yml not found at %s — using empty mapping", shims_path
        )
        return {}

    shims: dict[str, dict[str, str]] = {}
    current_key: str | None = None
    with open(shims_path, encoding='utf-8') as fh:
        for raw_line in fh:
            line = raw_line.rstrip('\n\r')
            if not line or line.startswith('#'):
                continue
            if not line[0].isspace():
                # Top-level key: "icon-name:"
                current_key = line.rstrip(':')
                shims[current_key] = {}
            elif current_key is not None:
                # Indented value: "  key: value"
                stripped = line.strip()
                if ':' in stripped:
                    k, _, v = stripped.partition(':')
                    shims[current_key][k.strip()] = v.strip()
    _logger.debug("fa4_to_fa7: loaded %d shim entries from %s", len(shims), shims_path)
    return shims


# ---------------------------------------------------------------------------
# Icon class transformation helpers
# ---------------------------------------------------------------------------

def _get_fa7_class(icon_name: str, shims: dict[str, dict[str, str]]) -> str:
    """Return full FA7 class string for a bare FA4 icon name (without 'fa-' prefix).

    Lookup order:
    1. Direct shim entry → use mapped prefix and/or name.
    2. Name ends with '-o' (FA4 outline convention) → Regular style, strip suffix.
    3. Not in shims → Solid, same name.
    """
    entry = shims.get(icon_name)
    if entry is not None:
        prefix = entry.get('prefix', 'fas')
        name = entry.get('name', icon_name)
        style = _PREFIX_MAP.get(prefix, 'fa-solid')
        return f'{style} fa-{name}'

    # FA4 "-o" outline suffix → Regular style
    if icon_name.endswith('-o'):
        base = icon_name[:-2]
        base_entry = shims.get(base, {})
        name = base_entry.get('name', base)
        return f'fa-regular fa-{name}'

    # Not in shims → Solid, same name (unchanged)
    return f'fa-solid fa-{icon_name}'


def _transform_icon_class(raw: str, shims: dict[str, dict[str, str]]) -> str:
    """Transform a single FA4 icon class token to the full FA7 class string.

    Handles:
    - 'fa-solid fa-house'   → 'fa-solid fa-house'    (full class string with base)
    - 'fa-envelope'  → 'fa-solid fa-envelope'  (bare icon name with prefix)
    - 'fa-warning'   → 'fa-solid fa-triangle-exclamation'  (via shim)

    Already-FA7 values ('fa-solid …', 'fa-regular …', 'fa-brands …') pass through unchanged.
    """
    cls = raw.strip()

    # Already FA7 — pass through (idempotent)
    if cls.startswith(('fa-solid', 'fa-regular', 'fa-brands')):
        return cls

    # "fa-solid fa-X" — full FA4 class string (base class + icon class)
    if cls.startswith('fa fa-'):
        return _get_fa7_class(cls[6:], shims)

    # "fa-X" — bare icon class only (no base class)
    if cls.startswith('fa-'):
        return _get_fa7_class(cls[3:], shims)

    # Unknown format — leave unchanged and log
    _logger.debug("fa4_to_fa7: unrecognised icon class %r — leaving unchanged", cls)
    return cls


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _table_exists(cr, table: str) -> bool:
    """Return True if *table* exists in the current DB schema."""
    cr.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = %s AND table_schema = 'public' LIMIT 1",
        [table],
    )
    return bool(cr.fetchone())


def _column_exists(cr, table: str, column: str) -> bool:
    """Return True if *column* exists in *table*."""
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s AND table_schema = 'public'
        LIMIT 1
        """,
        [table, column],
    )
    return bool(cr.fetchone())


# ---------------------------------------------------------------------------
# Per-field migration helpers
# ---------------------------------------------------------------------------

def _migrate_web_icons(cr, shims: dict[str, dict[str, str]]) -> None:
    """Migrate ir_ui_menu.web_icon from 'fa-solid fa-X,color,bg' to 'fa-STYLE fa-Y,color,bg'."""
    if not _column_exists(cr, 'ir_ui_menu', 'web_icon'):
        _logger.info("fa4_to_fa7: ir_ui_menu.web_icon column not found — skipping")
        return

    cr.execute("SELECT id, web_icon FROM ir_ui_menu WHERE web_icon LIKE 'fa fa-%'")
    rows = cr.fetchall()
    if not rows:
        _logger.info("fa4_to_fa7: ir_ui_menu.web_icon — no rows to migrate")
        return

    updates: list[tuple[str, int]] = []
    for menu_id, web_icon in rows:
        # Format: "fa-solid fa-X,foreground_color,background_color"  (color parts may be absent)
        parts = web_icon.split(',', 2)
        new_icon_class = _transform_icon_class(parts[0], shims)
        if new_icon_class != parts[0]:
            parts[0] = new_icon_class
            updates.append((','.join(parts), menu_id))

    if updates:
        cr.executemany("UPDATE ir_ui_menu SET web_icon = %s WHERE id = %s", updates)
        _logger.info("fa4_to_fa7: ir_ui_menu.web_icon — migrated %d records", len(updates))
    else:
        _logger.info("fa4_to_fa7: ir_ui_menu.web_icon — all records already FA7 format")


def _migrate_icon_field(
    cr,
    table: str,
    field: str,
    shims: dict[str, dict[str, str]],
    where_clause: str = '',
) -> None:
    """Migrate a DB field containing a bare FA4 icon class ('fa-X' or 'fa-solid fa-X') to FA7.

    Args:
        cr: Database cursor.
        table: Table name (safe: hardcoded by callers).
        field: Column name (safe: hardcoded by callers).
        shims: Icon mapping from shims.yml.
        where_clause: Optional extra WHERE filter (must include leading ' AND …').
    """
    if not _table_exists(cr, table):
        _logger.debug("fa4_to_fa7: table %r not found — skipping", table)
        return
    if not _column_exists(cr, table, field):
        _logger.debug("fa4_to_fa7: column %r.%r not found — skipping", table, field)
        return

    # Fetch all non-null values (table/field names are hardcoded by callers — no injection risk)
    cr.execute(
        f"SELECT id, {field} FROM {table} WHERE {field} IS NOT NULL{where_clause}",  # noqa: S608
        [],
    )
    rows = cr.fetchall()
    if not rows:
        _logger.info("fa4_to_fa7: %s.%s — no rows to migrate", table, field)
        return

    updates: list[tuple[str, int]] = []
    for row_id, icon_val in rows:
        new_val = _transform_icon_class(icon_val, shims)
        if new_val != icon_val:
            updates.append((new_val, row_id))

    if updates:
        cr.executemany(
            f"UPDATE {table} SET {field} = %s WHERE id = %s",  # noqa: S608
            updates,
        )
        _logger.info("fa4_to_fa7: %s.%s — migrated %d / %d records", table, field, len(updates), len(rows))
    else:
        _logger.info("fa4_to_fa7: %s.%s — all %d records already FA7 format", table, field, len(rows))


# ---------------------------------------------------------------------------
# Main migrate() entry point
# ---------------------------------------------------------------------------

def migrate(cr, version: str) -> None:
    """Upgrade all FA4 icon class strings in the database to FA7 native syntax.

    Called automatically by Odoo's migration framework when upgrading the
    web module from any version < 2.0 to 2.0.
    """
    shims = _load_shims()
    _logger.info(
        "fa4_to_fa7 DB migration starting (shims: %d entries, from_version: %s)",
        len(shims), version,
    )

    # --- Core tables (always present) ---

    # ir_ui_menu.web_icon — special format: "fa-solid fa-X,color,bg"
    _migrate_web_icons(cr, shims)

    # --- Optional tables (guarded) ---

    # mail.activity.type.icon — bare icon name "fa-X"
    _migrate_icon_field(cr, 'mail_activity_type', 'icon', shims)

    # onboarding.onboarding.step.done_icon — bare icon name "fa-X"
    _migrate_icon_field(cr, 'onboarding_onboarding_step', 'done_icon', shims)

    # website.configurator.feature.icon — bare icon name "fa-X"
    _migrate_icon_field(cr, 'website_configurator_feature', 'icon', shims)

    # sign.item.type.icon — bare icon name "fa-X"
    _migrate_icon_field(cr, 'sign_item_type', 'icon', shims)

    # hr.contract.salary.benefit.icon — full class "fa-solid fa-X"
    _migrate_icon_field(cr, 'hr_contract_salary_benefit', 'icon', shims)

    # remote.device.category.icon — bare icon name "fa-X"
    _migrate_icon_field(cr, 'remote_device_category', 'icon', shims)

    # base_credential_manager.icon — bare icon name "fa-X"
    _migrate_icon_field(cr, 'base_credential_manager', 'icon', shims)

    _logger.info("fa4_to_fa7 DB migration complete")
