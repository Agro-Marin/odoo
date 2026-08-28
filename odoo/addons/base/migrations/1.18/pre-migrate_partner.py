"""Rename ``contacts`` to ``partner``, and ``contacts_enterprise`` to ``partner_enterprise``.

The module fronts ``res.partner`` -- its action defaults ``is_company`` to true,
and its Configuration submenu owns countries, states, industries, tags and bank
accounts. It defines no model of its own, so unlike the renames at 1.11, 1.13,
1.16 and 1.17 there is no ``ir_model`` row, no table and no constraint to carry:
what moves is the module name, and the module name is the namespace half of
every xmlid the module owns.

**This has to run in base's own pre-migration.** A module's migration scripts are
found through its manifest, and after the rename there is no manifest at
``contacts``: the loader reads ``ir_module_module`` for a module it cannot find
on disk and skips it, migrations included. base's hook is the only one that still
fires, and it is the first the loader reaches. **It requires ``-u base``** --
``load_modules`` marks base *to upgrade* only when it is named, and a version
bump alone does not do it.

**Every substitution here is anchored on an enumerated xmlid.** That is the one
way this rename differs in kind from its predecessors. ``base_automation`` was a
unique token, so 1.17 could substitute it blindly across stored source. Here the
old name is a common English noun *and* a local variable: ``mass_mailing``'s
controller writes ``contacts.subscription_ids``, ``"contacts": contacts`` is a
QWeb render key, and the module's own help text ends a sentence with *"related to
your contacts."* -- which a bare ``contacts.`` -> ``partner.`` rule rewrites into
prose. So there is no prefix rule below, only the sixteen ids the module defines
and the two the enterprise bridge does.

``menu_contacts`` becomes ``partner_menu_root`` (the house spelling, as
``sale_menu_root``), ``res_partner_menu_contacts`` becomes ``res_partner_menu``,
and the four ``action_contacts*`` ids become ``action_partner*``. The other ten
never spelled the app name and keep theirs, changing only namespace.

The visible label does not move: the app is still called *Contacts*, the action
still answers on ``/odoo/contacts``. Only the technical name changes, the way
``stock`` is labelled *Inventory*.
"""

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

# The module directory is the first path component of ir_ui_view.arch_fs and the
# first comma-separated half of ir_ui_menu.web_icon. Both are anchored: a prefix
# match at position 0, never a substring search.
_WEB_ICON_RENAMES = {f"{old},": f"{new}," for old, new in _MODULE_RENAMES.items()}


def _qualified_pairs():
    """``old_module.old_id`` -> ``new_module.new_id`` for every id both modules own.

    Longest first, so ``contacts.action_contacts_view_tree`` is not eaten by
    ``contacts.action_contacts``, and ``contacts_enterprise.*`` is not eaten by
    ``contacts.*``.
    """
    pairs = []
    for old_mod, new_mod in _MODULE_RENAMES.items():
        for old_id, new_id in _XMLID_RENAMES.get(old_mod, {}).items():
            pairs.append((f"{old_mod}.{old_id}", f"{new_mod}.{new_id}"))
    return sorted(pairs, key=lambda kv: len(kv[0]), reverse=True)


_QUALIFIED_PAIRS = _qualified_pairs()


def _rename_modules(cr):
    renamed = 0
    for old, new in _MODULE_RENAMES.items():
        # A row under the new name can only exist if update_list() got here
        # first and created an uninstalled placeholder, or if this already ran.
        # ir_module_module.name is unique, so the stale row is what has to go.
        cr.execute(
            "DELETE FROM ir_module_module WHERE name = %s"
            " AND EXISTS (SELECT 1 FROM ir_module_module WHERE name = %s)",
            (old, new),
        )
        cr.execute("UPDATE ir_module_module SET name = %s WHERE name = %s", (new, old))
        renamed += cr.rowcount

        # UNIQUE (module_id, name): a tree updated halfway can name both.
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

        # ir.module.module rows are registered under base.module_<name> with
        # noupdate set, so nothing refreshes this one. Left behind, update_list()
        # creates the new xmlid and _process_end reaps this one -- taking the
        # module record itself with it.
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
    """Move the ids that spelled the old app name, inside their new namespace."""
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
    """``ir_ui_menu.web_icon`` stores ``<module>,static/description/icon.png``.

    Nothing derives this column from a file the loader re-reads unless the menu
    record itself is re-imported, and the menu's own xmlid has just moved, so
    rewrite it here rather than trusting the reload. Anchored on the comma: the
    module name is everything left of it.
    """
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
    """Rewrite the columns that *quote* one of the renamed xmlids.

    Stored source, not identity: view arch, the Python of a server action, a
    rule's domain, a saved filter. ``arch_db`` matters because the loader
    validates each view as it writes it against the views already in the table,
    so a sibling still naming ``contacts.action_contacts`` can fail the upgrade
    before its own reload. ``ir_act_server.code``, ``ir_rule.domain_force`` and
    the filter domains matter because no file derives them and nothing will ever
    rewrite them -- an administrator's server action calling
    ``env.ref("contacts.action_contacts")`` survives every upgrade, broken, until
    someone runs it.

    ``arch_fs`` is rewritten separately, by prefix: it is a path, and its first
    component is the module directory.
    """
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
    """The source path of a view leads with the module directory."""
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
    """Drop the per-file xmlid cache of both renamed modules.

    ``ir_module_module.data_file_checksums`` maps each data file to a content sha
    and the xmlids it created -- **fully qualified**, ``f"{module}.{name}"``. A
    rename changes no file's content, so the next upgrade finds the sha
    unchanged, takes the skip branch in ``load_data`` and seeds
    ``registry.loaded_xmlids`` with ``contacts.*`` while ``_process_end`` builds
    ``partner.*`` candidates from the rows this script just renamed. The sets
    cannot intersect, so every non-``noupdate`` record the module owns is reaped.
    Silently: INFO-level deletions, exit 0.

    This rename also renames the data files themselves, which changes the cache
    key and would dodge the trap by accident. That is not a reason to omit the
    statement -- it is a reason it must not be relied on. ``NULL`` is the
    spelling ``module_uninstall()`` already uses.

    A fresh-install test cannot show any of this: ``track`` requires
    ``mode == "update"``, so a module that has only ever been installed has no
    checksums to go stale.
    """
    cr.execute(
        "UPDATE ir_module_module SET data_file_checksums = NULL"
        " WHERE name = ANY(%s) AND data_file_checksums IS NOT NULL",
        (list(_MODULE_RENAMES.values()),),
    )
    return cr.rowcount


def _survivors(cr):
    """Anything still spelling an old name in a table that keys on it.

    Reported rather than repaired: a leftover means this script's map is
    incomplete, and a silent partial rename is what produces a database whose
    xmlids resolve to nothing months later.
    """
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
