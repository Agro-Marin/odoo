"""Rename the three mixin-only modules onto the ``mixin_`` prefix their models use.

``base_attribute_mixin`` -> ``mixin_attribute``, ``base_encryption_mixin`` ->
``mixin_encryption``, ``base_recurrence`` -> ``mixin_recurrence``.

All three ship abstract mixins and nothing else -- no concrete model, no data
file, no view, no menu. Their models have been ``mixin.attribute``,
``mixin.attribute.line``, ``mixin.attribute.value``, ``mixin.encryption`` and
``mixin.recurrence.rule`` all along, so what moves here is only the module name
catching up to the models it has always declared.

``base_`` means *below the module it serves* in this fork -- the reading 1.11
and 1.14 argue for base_account and base_order, and the reason those two comments
still spell ``base_recurrence``. That is the prefix these three could never
earn: a mixin serves whoever inherits it and sits below nobody in particular.
Two of them said so twice over, carrying ``base_`` and ``_mixin`` at once.

**This has to run in base's own pre-migration.** A module's migration scripts are
found through its manifest, and after the rename there is no manifest at the old
name: the loader reads ``ir_module_module`` for a module it cannot find on disk
and skips it, migrations included. base's hook is the only one that still fires,
and it is the first the loader reaches. It requires ``-u base`` -- a version bump
alone does not mark base to upgrade.

Narrower than the renames at 1.11, 1.13, 1.16, 1.17 and 1.18, and narrow in a way
worth stating so the next reader does not go looking for the missing halves. A
sweep of every text-typed column of an installed database finds the old names in
exactly four places, all of them handled here: ``ir_module_module.name``,
``ir_module_module_dependency.name``, ``ir_model_data.module`` and the
``base.module_<name>`` rows in ``ir_model_data.name``. There is no
``ir_ui_view.arch_db`` to rewrite, no ``arch_fs`` path, no ``ir_ui_menu.web_icon``,
no ``ir_act_server.code`` and no stored source quoting an id, because the modules
contribute none of those. Nor is there an xmlid that spells the old module name:
every id they own is generated from a *model* name that is not changing.

**The adopted ids are not all about the mixins' own models.** Of the 43 that
``base_attribute_mixin`` owns in a database with ``product`` installed, ten
describe ``product``'s concrete tables --
``selection__product_attribute__display_type__*``,
``constraint_product_attribute_value_name_src_uniq``,
``model_inherit__product_attribute__mixin_catalog`` -- because Odoo attributes a
reflected id to the module that *declared* the field, not to the model that ends
up carrying it. Left under a module name nothing on disk answers to, they are
orphans, and ``_process_end`` reaps orphans: an ``ir.model.fields`` row takes its
column with it, and a reaped ``ir.model.fields.selection`` row leaves the column
in place holding values nothing can render. That is what the single
``ir_model_data.module`` update below is protecting, and it is why it must run
before ``update_list()`` sees the new directories.
"""

import logging

_logger = logging.getLogger(__name__)

_MODULE_RENAMES = {
    "base_attribute_mixin": "mixin_attribute",
    "base_encryption_mixin": "mixin_encryption",
    "base_recurrence": "mixin_recurrence",
}


def _rename_modules(cr):
    renamed = 0
    adopted = 0
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
        adopted += cr.rowcount

    # ir_model_constraint.module and ir_model_relation.module are integer FKs to
    # ir_module_module.id, and the id does not move, so those rows follow the
    # rename on their own.
    return renamed, adopted


def _reset_data_file_checksums(cr):
    """Drop the per-file xmlid cache of both renamed modules.

    ``ir_module_module.data_file_checksums`` maps each data file to a content sha
    and the xmlids it created -- **fully qualified**, ``f"{module}.{name}"``. A
    rename changes no file's content, so the next upgrade finds the sha
    unchanged, takes the skip branch in ``load_data`` and seeds
    ``registry.loaded_xmlids`` with the old namespace while ``_process_end``
    builds new-namespace candidates from the rows renamed above. The sets cannot
    intersect, so every non-``noupdate`` record the module owns is reaped --
    silently, at INFO level, exit 0.

    **None of the three modules here has a data file, so this cannot fire.** It is kept
    because that is a property of these two modules today and not of the rename,
    and because ``NULL`` is the spelling ``module_uninstall()`` already uses. Do
    not read a green upgrade as evidence that it works: on this rename the
    control run is negative either way.
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
        ("ir_module_module_exclusion", "name"),
        ("ir_model_data", "module"),
    ):
        cr.execute(
            f"SELECT count(*) FROM {table} WHERE {column} = ANY(%s)",
            (list(_MODULE_RENAMES),),
        )
        (count,) = cr.fetchone()
        if count:
            found.append(f"{table}.{column}={count}")

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

    renamed, adopted = _rename_modules(cr)
    checksums = _reset_data_file_checksums(cr)

    _logger.info(
        "base 1.19: renamed %s module(s) %s, carrying over %s external "
        "identifier(s) and dropping the data-file xmlid cache of %s module(s)",
        renamed,
        ", ".join(f"{o} -> {n}" for o, n in _MODULE_RENAMES.items()),
        adopted,
        checksums,
    )

    survivors = _survivors(cr)
    if survivors:
        _logger.warning(
            "base 1.19: the rename left the old names behind in %s -- the map in "
            "this script is incomplete and those rows will resolve to nothing",
            ", ".join(survivors),
        )
