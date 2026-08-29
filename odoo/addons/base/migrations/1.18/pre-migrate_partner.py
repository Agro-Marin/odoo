import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_MODULE_RENAMES = {
    "contacts": "partner",
    "contacts_enterprise": "partner_enterprise",
}

_XMLID_RENAMES = {
    "contacts": {
        "action_contacts": "action_partner",
        "action_contacts_view_form": "action_partner_view_form",
        "action_contacts_view_kanban": "action_partner_view_kanban",
        "action_contacts_view_tree": "action_partner_view_tree",
        "menu_contacts": "partner_menu_root",
        "res_partner_menu_contacts": "res_partner_menu",
    },
    "contacts_enterprise": {
        "res_partner_action_contacts_view_map": "res_partner_action_partner_view_map",
    },
}

_WEB_ICON_RENAMES = {f"{old},": f"{new}," for old, new in _MODULE_RENAMES.items()}


def _qualified_pairs():
    pairs = []
    for old_mod, new_mod in _MODULE_RENAMES.items():
        for old_id, new_id in _XMLID_RENAMES.get(old_mod, {}).items():
            pairs.append((f"{old_mod}.{old_id}", f"{new_mod}.{new_id}"))
    return sorted(pairs, key=lambda kv: len(kv[0]), reverse=True)


_QUALIFIED_PAIRS = _qualified_pairs()


def _rename_modules(cr):
    renamed = 0
    for old, new in _MODULE_RENAMES.items():
        cr.execute(
            "DELETE FROM ir_module_module WHERE name = %s"
            " AND EXISTS (SELECT 1 FROM ir_module_module WHERE name = %s)",
            (old, new),
        )
        cr.execute("UPDATE ir_module_module SET name = %s WHERE name = %s", (new, old))
        renamed += cr.rowcount

        cr.execute(
            "DELETE FROM ir_module_module_dependency d WHERE d.name = %s"
            " AND EXISTS (SELECT 1 FROM ir_module_module_dependency o"
            "              WHERE o.name = %s AND o.module_id = d.module_id)",
            (old, new),
        )
        cr.execute(
            "UPDATE ir_module_module_dependency SET name = %s WHERE name = %s",
            (new, old),
        )
        cr.execute(
            "DELETE FROM ir_module_module_exclusion e WHERE e.name = %s"
            " AND EXISTS (SELECT 1 FROM ir_module_module_exclusion o"
            "              WHERE o.name = %s AND o.module_id = e.module_id)",
            (old, new),
        )
        cr.execute(
            "UPDATE ir_module_module_exclusion SET name = %s WHERE name = %s",
            (new, old),
        )

        cr.execute(
            "DELETE FROM ir_model_data WHERE module = 'base' AND name = %s"
            " AND EXISTS (SELECT 1 FROM ir_model_data"
            "              WHERE module = 'base' AND name = %s)",
            (f"module_{old}", f"module_{new}"),
        )
        cr.execute(
            "UPDATE ir_model_data SET name = %s"
            " WHERE module = 'base' AND model = 'ir.module.module' AND name = %s",
            (f"module_{new}", f"module_{old}"),
        )

        cr.execute("UPDATE ir_model_data SET module = %s WHERE module = %s", (new, old))
    return renamed


def _rename_xmlids(cr):
    moved = 0
    for old_mod, renames in _XMLID_RENAMES.items():
        new_mod = _MODULE_RENAMES[old_mod]
        for old_id, new_id in renames.items():
            cr.execute(
                "DELETE FROM ir_model_data stale WHERE stale.module = %s"
                " AND stale.name = %s"
                " AND EXISTS (SELECT 1 FROM ir_model_data kept"
                "              WHERE kept.module = %s AND kept.name = %s)",
                (new_mod, old_id, new_mod, new_id),
            )
            cr.execute(
                "UPDATE ir_model_data SET name = %s WHERE module = %s AND name = %s",
                (new_id, new_mod, old_id),
            )
            moved += cr.rowcount
    return moved


def _rename_web_icon(cr):
    if not schema.column_exists(cr, "ir_ui_menu", "web_icon"):
        return 0
    rewritten = 0
    for old, new in _WEB_ICON_RENAMES.items():
        cr.execute(
            "UPDATE ir_ui_menu SET web_icon = %s || substring(web_icon FROM %s)"
            " WHERE web_icon LIKE %s",
            (new, len(old) + 1, old + "%"),
        )
        rewritten += cr.rowcount
    return rewritten


def _sweep_source_text(cr):
    columns = (
        ("ir_ui_view", "arch_db", True),
        ("ir_ui_view", "arch_prev", False),
        ("ir_act_server", "code", False),
        ("ir_rule", "domain_force", False),
        ("ir_filters", "domain", False),
        ("ir_filters", "context", False),
        ("ir_act_window", "domain", False),
        ("ir_act_window", "context", False),
    )
    rewritten = 0
    for table, column, is_jsonb in columns:
        if not schema.column_exists(cr, table, column):
            continue
        cast = "::text" if is_jsonb else ""
        back = "::jsonb" if is_jsonb else ""
        for old, new in _QUALIFIED_PAIRS:
            cr.execute(
                f"UPDATE {table} SET {column} = replace({column}{cast}, %s, %s){back}"
                f" WHERE {column}{cast} LIKE %s",
                (old, new, f"%{old}%"),
            )
            rewritten += cr.rowcount
    return rewritten


def _rename_arch_fs(cr):
    if not schema.column_exists(cr, "ir_ui_view", "arch_fs"):
        return 0
    rewritten = 0
    for old, new in _MODULE_RENAMES.items():
        cr.execute(
            "UPDATE ir_ui_view SET arch_fs = %s || substring(arch_fs FROM %s)"
            " WHERE arch_fs LIKE %s",
            (new, len(old) + 1, f"{old}/%"),
        )
        rewritten += cr.rowcount
    return rewritten


def _reset_data_file_checksums(cr):
    cr.execute(
        "UPDATE ir_module_module SET data_file_checksums = NULL"
        " WHERE name = ANY(%s) AND data_file_checksums IS NOT NULL",
        (list(_MODULE_RENAMES.values()),),
    )
    return cr.rowcount


def _survivors(cr):
    found = []
    for table, column in (
        ("ir_module_module", "name"),
        ("ir_module_module_dependency", "name"),
        ("ir_model_data", "module"),
    ):
        cr.execute(
            f"SELECT count(*) FROM {table} WHERE {column} = ANY(%s)",
            (list(_MODULE_RENAMES),),
        )
        (count,) = cr.fetchone()
        if count:
            found.append(f"{table}.{column}={count}")

    for old, _new in _QUALIFIED_PAIRS:
        cr.execute(
            "SELECT count(*) FROM ir_ui_view WHERE arch_db::text LIKE %s", (f"%{old}%",)
        )
        (count,) = cr.fetchone()
        if count:
            found.append(f"ir_ui_view.arch_db~{old}={count}")

    cr.execute(
        "SELECT count(*) FROM ir_model_data WHERE module = 'base' AND name = ANY(%s)",
        ([f"module_{old}" for old in _MODULE_RENAMES],),
    )
    (count,) = cr.fetchone()
    if count:
        found.append(f"ir_model_data.base.module_*={count}")
    return found


def migrate(cr, version):
    if not version:
        return

    modules = _rename_modules(cr)
    xmlids = _rename_xmlids(cr)
    icons = _rename_web_icon(cr)
    paths = _rename_arch_fs(cr)
    quoted = _sweep_source_text(cr)
    checksums = _reset_data_file_checksums(cr)

    _logger.info(
        "base 1.18: renamed %s module(s) %s, moved %s xmlid(s) that spelled the old "
        "app name, rewrote %s menu web_icon(s), %s view source path(s) and %s row(s) "
        "of stored source quoting a renamed id, and dropped the data-file xmlid "
        "cache of %s module(s)",
        modules,
        ", ".join(f"{o} -> {n}" for o, n in _MODULE_RENAMES.items()),
        xmlids,
        icons,
        paths,
        quoted,
        checksums,
    )

    survivors = _survivors(cr)
    if survivors:
        _logger.warning(
            "base 1.18: the rename left the old names behind in %s -- the map in "
            "this script is incomplete and those rows will resolve to nothing",
            ", ".join(survivors),
        )
