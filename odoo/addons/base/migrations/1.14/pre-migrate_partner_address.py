import logging

_logger = logging.getLogger(__name__)

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
    cr.execute("DELETE FROM ir_module_module WHERE id = %s", (module_id,))


def _relink(cr, old, new):
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
        _drop_stub(cr, clash_id)

    cr.execute("UPDATE ir_module_module SET name = %s WHERE name = %s", (_NEW, _OLD))
    relinked = _relink(cr, _OLD, _NEW)

    cr.execute("UPDATE ir_model_data SET module = %s WHERE module = %s", (_NEW, _OLD))
    adopted = cr.rowcount

    cr.execute(
        """
        UPDATE ir_model_data SET name = %s
         WHERE module = 'base' AND model = 'ir.module.module' AND name = %s
        """,
        (f"module_{_NEW}", f"module_{_OLD}"),
    )

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
