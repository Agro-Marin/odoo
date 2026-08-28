import logging

_logger = logging.getLogger(__name__)

# base_iban and base_vat both depend on account, which puts them above it in the
# graph -- the reverse of what base_ means in this fork, where base_account,
# base_order and base_recurrence all sit below the module they serve. They are
# account_iban and account_vat now, beside the other account_* modules
# that already consumed them (account_iso20022, account_qr_code_sepa,
# account_sepa_direct_debit).
#
# This has to run in base's own pre-migration and cannot live in either renamed
# module: a migration script only runs for a module that already carries a
# db_version, and account_iban has none -- to the loader it is a module nobody
# has ever installed. Left alone, update_list() would never even visit the
# base_iban row, because it iterates the manifests found on disk (ir_module.py,
# update_list) and there is no base_iban manifest any more. The old row would
# keep state='installed' with no code behind it while account_iban installed
# fresh beside it and created a second copy of every record the old module
# owned. Nothing would clean up after it either: _process_end reaps orphans
# only WHERE module = ANY(updated_modules), and base_iban is not among them.
# The visible result is not a crash but a res.partner.bank form that inherits
# the iban widget patch twice.
_RENAMED_MODULES = {
    "base_iban": "account_iban",
    "base_vat": "account_vat",
}

# base_vat spelled its own module name into a record id, so renaming the module
# alone would leave account_vat.view_partner_base_vat_form behind. l10n_in owns
# a separate l10n_in_view_partner_base_vat_form that deliberately keeps its
# name: that record belongs to l10n_in, not here.
_RENAMED_XMLIDS = {
    "account_vat": {
        "view_partner_base_vat_form": "view_partner_account_vat_form",
    },
}


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
    cr.execute(
        """
        DELETE FROM ir_module_module_dependency stale
         WHERE stale.name = %s
           AND EXISTS (
               SELECT 1 FROM ir_module_module_dependency kept
                WHERE kept.module_id = stale.module_id AND kept.name = %s
           )
        """,
        (old, new),
    )
    cr.execute(
        "UPDATE ir_module_module_dependency SET name = %s WHERE name = %s",
        (new, old),
    )
    relinked = cr.rowcount
    cr.execute(
        """
        DELETE FROM ir_module_module_exclusion stale
         WHERE stale.name = %s
           AND EXISTS (
               SELECT 1 FROM ir_module_module_exclusion kept
                WHERE kept.module_id = stale.module_id AND kept.name = %s
           )
        """,
        (old, new),
    )
    cr.execute(
        "UPDATE ir_module_module_exclusion SET name = %s WHERE name = %s",
        (new, old),
    )
    return relinked + cr.rowcount


def _rename_module(cr, old, new):
    if not _module_row(cr, old):
        return None

    if clash := _module_row(cr, new):
        clash_id, clash_state = clash
        if clash_state != "uninstalled":
            _logger.error(
                "base 1.11: cannot rename %s to %s -- %s is already %s in this "
                "database, so both modules own a copy of the same records. "
                "Uninstall %s, then upgrade base again.",
                old,
                new,
                new,
                clash_state,
                new,
            )
            return None
        # update_list() reached the renamed directories before this migration
        # did: it found no base_* manifest, left the old row untouched and
        # created a fresh uninstalled row for the new name beside it. An
        # uninstalled module owns no ir_model_data of its own, so the stub is
        # safe to drop and let the real row take the name.
        _drop_stub(cr, clash_id)
        _logger.info(
            "base 1.11: dropped the uninstalled %s placeholder left by an "
            "earlier module-list refresh",
            new,
        )

    cr.execute("UPDATE ir_module_module SET name = %s WHERE name = %s", (new, old))

    # data_file_checksums caches, per data file, the sha of its content and the
    # xmlids that file created -- fully qualified, so "base_iban.<name>".
    # Renaming the module changes no file content, so the next upgrade finds the
    # sha unchanged, skips the file and feeds those OLD-namespace xmlids into
    # registry.loaded_xmlids, while _process_end builds the candidates from
    # ir_model_data as NEW-namespace "account_iban.<name>". The two sets cannot
    # intersect, so every non-noupdate record the module owns is reaped -- views,
    # menus, actions and ACLs, silently, at INFO and exit code 0. Dropping the
    # cache forces one full re-import under the new name. module_uninstall()
    # spells it the same way, and for the same reason.
    cr.execute(
        "UPDATE ir_module_module SET data_file_checksums = NULL WHERE name = %s",
        (new,),
    )

    relinked = _relink(cr, old, new)

    cr.execute("UPDATE ir_model_data SET module = %s WHERE module = %s", (new, old))
    adopted = cr.rowcount

    # ir.module.module records are registered by ir_module.create() under
    # base.module_<name>, with noupdate set, so nothing refreshes this one.
    cr.execute(
        """
        UPDATE ir_model_data SET name = %s
         WHERE module = 'base' AND model = 'ir.module.module' AND name = %s
        """,
        (f"module_{new}", f"module_{old}"),
    )

    for old_xmlid, new_xmlid in _RENAMED_XMLIDS.get(new, {}).items():
        cr.execute(
            "UPDATE ir_model_data SET name = %s WHERE module = %s AND name = %s",
            (new_xmlid, new, old_xmlid),
        )

    return relinked, adopted


def migrate(cr, version):
    for old, new in _RENAMED_MODULES.items():
        if (result := _rename_module(cr, old, new)) is None:
            continue
        relinked, adopted = result
        _logger.info(
            "base 1.11: renamed module %s to %s, carrying over %s external "
            "identifier(s) and repointing %s manifest link(s)",
            old,
            new,
            adopted,
            relinked,
        )
