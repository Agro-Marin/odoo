import logging

_logger = logging.getLogger(__name__)

_RENAMED_MODULES = {
    "base_iban": "account_iban",
    "base_vat": "account_vat",
}

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
    cr.execute("DELETE FROM ir_module_module WHERE id = %s", (module_id,))


def _relink(cr, old, new):
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
        _drop_stub(cr, clash_id)
        _logger.info(
            "base 1.11: dropped the uninstalled %s placeholder left by an "
            "earlier module-list refresh",
            new,
        )

    cr.execute("UPDATE ir_module_module SET name = %s WHERE name = %s", (new, old))

    cr.execute(
        "UPDATE ir_module_module SET data_file_checksums = NULL WHERE name = %s",
        (new,),
    )

    relinked = _relink(cr, old, new)

    cr.execute("UPDATE ir_model_data SET module = %s WHERE module = %s", (new, old))
    adopted = cr.rowcount

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
