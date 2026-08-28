import logging

_logger = logging.getLogger(__name__)

# base_address_extended depends on contacts, which puts it above contacts in the
# graph -- the reverse of what base_ means in this fork, where base_account,
# base_order and base_recurrence all sit below the module they serve. It owns
# res.city, res.country.enforce_cities and the stored street_name /
# street_number / street_number2 split on res.partner, so it is a partner
# module: partner_address_extended, beside partner_autocomplete,
# partner_relationship and partner_scoring.
#
# This has to run in base's own pre-migration and cannot live in the renamed
# module: a migration script only runs for a module the loader can find on disk,
# and after the rename there is no base_address_extended manifest. update_list()
# iterates the manifests it finds, so it would never visit the old row at all --
# leaving it state='installed' with no code behind it while
# partner_address_extended installs fresh beside it and creates a second copy of
# every record the old module owned.
_OLD = "base_address_extended"
_NEW = "partner_address_extended"


def _module_row(cr, name):
    cr.execute("SELECT id, state FROM ir_module_module WHERE name = %s", (name,))
    return cr.fetchone()


def _drop_stub(cr, module_id):
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'base' AND model = 'ir.module.module' AND res_id = %s
        """,
        (module_id,),
    )
    # ir_module_module_dependency.module_id and .exclusion are ondelete=cascade,
    # so the stub's own link rows go with it.
    cr.execute("DELETE FROM ir_module_module WHERE id = %s", (module_id,))


def _relink(cr, old, new):
    # UNIQUE (module_id, name) on both link tables: a module naming the old and
    # the new module at once would collide on the UPDATE. Nothing declares both
    # today, but a tree updated halfway can produce it.
    relinked = 0
    for table in ("ir_module_module_dependency", "ir_module_module_exclusion"):
        cr.execute(
            f"""
            DELETE FROM {table} stale
             WHERE stale.name = %s
               AND EXISTS (
                   SELECT 1 FROM {table} kept
                    WHERE kept.module_id = stale.module_id AND kept.name = %s
               )
            """,
            (old, new),
        )
        cr.execute(f"UPDATE {table} SET name = %s WHERE name = %s", (new, old))
        relinked += cr.rowcount
    return relinked


def migrate(cr, version):
    if not version:
        return

    if not _module_row(cr, _OLD):
        return

    if clash := _module_row(cr, _NEW):
        clash_id, clash_state = clash
        if clash_state != "uninstalled":
            _logger.error(
                "base 1.14: cannot rename %s to %s -- %s is already %s in this "
                "database, so both modules own a copy of the same records. "
                "Uninstall %s, then upgrade base again.",
                _OLD,
                _NEW,
                _NEW,
                clash_state,
                _NEW,
            )
            return
        # update_list() reached the renamed directory before this migration did:
        # it found no base_address_extended manifest, left the old row untouched
        # and created a fresh uninstalled row for the new name beside it. An
        # uninstalled module owns no ir_model_data of its own, so the stub is
        # safe to drop and let the real row take the name.
        _drop_stub(cr, clash_id)

    cr.execute("UPDATE ir_module_module SET name = %s WHERE name = %s", (_NEW, _OLD))
    relinked = _relink(cr, _OLD, _NEW)

    cr.execute("UPDATE ir_model_data SET module = %s WHERE module = %s", (_NEW, _OLD))
    adopted = cr.rowcount

    # ir.module.module records are registered by ir_module.create() under
    # base.module_<name>, with noupdate set, so nothing refreshes this one.
    cr.execute(
        """
        UPDATE ir_model_data SET name = %s
         WHERE module = 'base' AND model = 'ir.module.module' AND name = %s
        """,
        (f"module_{_NEW}", f"module_{_OLD}"),
    )

    # data_file_checksums is keyed by manifest-relative filename and stores, per
    # file, a content-only sha plus the FULLY QUALIFIED xmlids that file created
    # -- spelled with the old module name. Renaming the module changes no file
    # content, so on the next upgrade load_data() finds every sha unchanged,
    # skips the files, and feeds registry.loaded_xmlids the old-namespace ids.
    # _process_end then reads this module's ir_model_data rows, builds
    # module || '.' || name in the NEW namespace, finds none of them in
    # loaded_xmlids and deletes them. Measured on a real database: 37 rows down
    # to 30, res.city left with zero ir.model.access rows, menu, action and
    # three views gone, odoo-bin exit code 0 and nothing above INFO in the log.
    # Skipping unchanged files is the default (config.py, skip_unchanged_data_files
    # my_default=True), so this is the normal path, not an opt-in one.
    # Clearing forces a full re-import under the new name, which is also what
    # ir_module.module_uninstall() does for the same reason.
    #
    # That re-import is also why nothing here rewrites ir_ui_view.arch_fs. The
    # renamed directory is changed content, so the module is upgraded in this
    # same run; the cleared checksums make it re-convert every data file, and
    # _load_xml rewrites arch_fs from wherever each record is now defined.
    # Measured with an explicit UPDATE removed: 4 stale rows before, 0 after,
    # the renamed view file included -- a record whose basename changed is
    # matched by xmlid, not by path, so it repairs itself like the rest.
    cr.execute(
        "UPDATE ir_module_module SET data_file_checksums = NULL WHERE name = %s",
        (_NEW,),
    )

    _logger.info(
        "base 1.14: renamed module %s to %s, carrying over %s external "
        "identifier(s) and repointing %s manifest link(s), and cleared the "
        "data-file checksums so this upgrade re-imports under the new name",
        _OLD,
        _NEW,
        adopted,
        relinked,
    )
