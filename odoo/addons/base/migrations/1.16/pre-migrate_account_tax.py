import logging

_logger = logging.getLogger(__name__)

# base_tax defines account.tax, account.tax.group and account.tax.repartition.line;
# account only _inherit-s them. It is account_tax now, named for what it owns
# rather than for where it sits in the graph.
#
# That makes it the odd one out among the base_ -> account_ renames landing in
# this release. base_iban and base_vat moved because they depend on account and
# so contradicted the prefix; base_tax never did -- account depends on IT. The
# consequence to know: the account_ prefix no longer tells you which way the
# dependency runs. account_tax is below account, while account_tax_python and
# account_update_tax_tags are above it.
#
# This runs in base's pre-migration rather than in the module's own migrations/
# because a script only runs for a module that already carries a db_version, and
# to the loader account_tax is a module nobody has ever installed. Left alone,
# update_list() would never visit the base_tax row at all -- it iterates the
# manifests found on disk, and there is no base_tax manifest any more -- so the
# old row would keep state='installed' with no code behind it while account_tax
# installed fresh beside it and created a second copy of every record it owns.
#
# It gets its own version directory rather than joining an earlier one because
# _migration_applies (odoo/modules/migration.py) ends with
# `parsed_installed < full_version <= parsed_target`. Once a release has shipped
# base at version N, every database records db_version N, and a script added to
# N/ afterwards is tested `N < N` and silently never runs. One rename, one
# version.
_OLD = "base_tax"
_NEW = "account_tax"


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


def _relink(cr, table):
    # UNIQUE (module_id, name): a module naming the old and the new module at
    # once would collide on the UPDATE. Nothing declares both today, but a tree
    # updated halfway can produce it.
    cr.execute(
        f"""
        DELETE FROM {table} stale
         WHERE stale.name = %s
           AND EXISTS (
               SELECT 1 FROM {table} kept
                WHERE kept.module_id = stale.module_id AND kept.name = %s
           )
        """,
        (_OLD, _NEW),
    )
    cr.execute(f"UPDATE {table} SET name = %s WHERE name = %s", (_NEW, _OLD))
    return cr.rowcount


def migrate(cr, version):
    if not _module_row(cr, _OLD):
        return

    if clash := _module_row(cr, _NEW):
        clash_id, clash_state = clash
        if clash_state != "uninstalled":
            _logger.error(
                "base 1.16: cannot rename %s to %s -- %s is already %s in this "
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
        # it found no base_tax manifest, left the old row untouched and created a
        # fresh uninstalled row for the new name beside it. An uninstalled module
        # owns no ir_model_data, so the stub is safe to drop.
        _drop_stub(cr, clash_id)
        _logger.info(
            "base 1.16: dropped the uninstalled %s placeholder left by an "
            "earlier module-list refresh",
            _NEW,
        )

    cr.execute("UPDATE ir_module_module SET name = %s WHERE name = %s", (_NEW, _OLD))

    # data_file_checksums caches, per data file, the sha of its content and the
    # xmlids that file created -- fully qualified, so "base_tax.<name>". A rename
    # changes no file content, so the next upgrade finds the sha unchanged, skips
    # the file (modules/loading.py) and feeds those OLD-namespace xmlids into
    # registry.loaded_xmlids, while _process_end builds its candidates from
    # ir_model_data as NEW-namespace "account_tax.<name>". The two sets cannot
    # intersect, so every non-noupdate record the module owns is reaped -- here
    # that is the six ACLs in security/ir.model.access.csv, silently, at INFO
    # and exit code 0. Dropping the cache forces one full re-import under the new
    # name. module_uninstall() spells it the same way, and for the same reason.
    cr.execute(
        "UPDATE ir_module_module SET data_file_checksums = NULL WHERE name = %s",
        (_NEW,),
    )

    relinked = _relink(cr, "ir_module_module_dependency")
    relinked += _relink(cr, "ir_module_module_exclusion")

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

    # base_tax spells its own module name into no record id -- its external
    # identifiers are access_account_tax* and model_account_tax*, all already
    # named for the models -- so there is no xmlid rename map here.
    _logger.info(
        "base 1.16: renamed module %s to %s, carrying over %s external "
        "identifier(s) and repointing %s manifest link(s)",
        _OLD,
        _NEW,
        adopted,
        relinked,
    )
