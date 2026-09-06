import logging

_logger = logging.getLogger(__name__)

_PLACEHOLDER_STATES = ("uninstalled", "to install")

_RENAMES = {
    "account_extract": "extract_account",
    "account_extract_purchase": "extract_account_purchase",
    "hr_recruitment_extract": "extract_hr_recruitment",
    "hr_recruitment_extract_skills": "extract_hr_recruitment_skills",
    "hr_expense_extract": "extract_hr_expense",
    "hr_expense_extract_predict": "extract_hr_expense_predict",
}


def migrate(cr, version):
    if not version:
        return
    for old, new in _RENAMES.items():
        _rename_module(cr, old, new)


def _rename_module(cr, old, new):
    cr.execute(
        "SELECT id, state, db_version FROM ir_module_module WHERE name = %s", (old,)
    )
    old_row = cr.fetchone()
    if not old_row:
        return
    old_id = old_row[0]

    cr.execute("SELECT id, state FROM ir_module_module WHERE name = %s", (new,))
    existing = cr.fetchone()
    if existing and existing[1] not in _PLACEHOLDER_STATES:
        _logger.warning(
            "Not renaming %s -> %s: %s already exists in state %r, which is not "
            "a placeholder. Both carry data; resolve it by hand.",
            old,
            new,
            new,
            existing[1],
        )
        return

    cr.execute("UPDATE ir_model_data SET module = %s WHERE module = %s", (new, old))
    _logger.info(
        "Renamed ir_model_data module: %s -> %s (%d rows)", old, new, cr.rowcount
    )
    cr.execute(
        "UPDATE ir_module_module_dependency SET name = %s WHERE name = %s", (new, old)
    )
    _logger.info(
        "Renamed ir_module_module_dependency: %s -> %s (%d rows)", old, new, cr.rowcount
    )

    if existing:
        _adopt_placeholder(cr, old, new, old_row, existing)
    else:
        _rename_row(cr, old, new, old_id)


def _rename_row(cr, old, new, old_id):
    cr.execute("UPDATE ir_module_module SET name = %s WHERE id = %s", (new, old_id))
    _logger.info("Renamed ir_module_module: %s -> %s (id %s)", old, new, old_id)

    cr.execute(
        """
        UPDATE ir_model_data SET name = %s
         WHERE module = 'base' AND model = 'ir.module.module' AND name = %s
        """,
        (f"module_{new}", f"module_{old}"),
    )
    _logger.info("Renamed base.module_%s -> base.module_%s", old, new)


def _adopt_placeholder(cr, old, new, old_row, existing):
    old_id, old_state, old_db_version = old_row
    new_id, new_state = existing

    cr.execute(
        "UPDATE ir_module_module SET state = %s, db_version = %s WHERE id = %s",
        (old_state, old_db_version, new_id),
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'base' AND model = 'ir.module.module' AND name = %s
        """,
        (f"module_{old}",),
    )
    cr.execute("DELETE FROM ir_module_module WHERE id = %s", (old_id,))
    _logger.info(
        "Adopted the %r placeholder for %s (id %s) with state %r and db_version "
        "%r from %s (id %s), which was dropped",
        new_state,
        new,
        new_id,
        old_state,
        old_db_version,
        old,
        old_id,
    )
