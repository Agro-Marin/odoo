import logging

_logger = logging.getLogger(__name__)

#: The consumers were named after the model they extend and now carry the
#: framework's own prefix, so the family sorts and reads as one -- the shape
#: `documents_account` / `documents_hr` already uses. This module is where the
#: rename lives because it is installed wherever any of them is.
_RENAMES = {
    "account_document_extract": "document_extract_account",
    "account_document_extract_purchase": "document_extract_account_purchase",
    "hr_recruitment_document_extract": "document_extract_hr_recruitment",
    "hr_recruitment_document_extract_skills": "document_extract_hr_recruitment_skills",
    "hr_expense_document_extract": "document_extract_hr_expense",
    "hr_expense_document_extract_predict": "document_extract_hr_expense_predict",
}


def migrate(cr, version):
    if not version:
        return
    for old, new in _RENAMES.items():
        _rename_module(cr, old, new)


def _rename_module(cr, old, new):
    cr.execute("SELECT id FROM ir_module_module WHERE name = %s", (old,))
    if not cr.fetchone():
        return

    # A module-list update runs before migrations and creates an `uninstalled`
    # row for every module it finds on disk, so the new name is normally
    # already there and the rename would collide with it. Dropping that
    # placeholder is safe; an *installed* row under the new name is not a
    # placeholder, and renaming onto it would raise UniqueViolation and take
    # the registry down mid-upgrade. Say so and leave both alone instead.
    cr.execute("SELECT state FROM ir_module_module WHERE name = %s", (new,))
    existing = cr.fetchone()
    if existing and existing[0] != "uninstalled":
        _logger.warning(
            "Not renaming %s -> %s: %s already exists in state %r. Both are "
            "installed, which is not a rename; resolve it by hand.",
            old,
            new,
            new,
            existing[0],
        )
        return
    if existing:
        cr.execute("DELETE FROM ir_module_module WHERE name = %s", (new,))
        # And the xmlid that scan created for it. Left behind, it collides
        # with the rename of the old module's own xmlid further down -- the
        # key `(base, module_<new>)` would then exist twice.
        cr.execute(
            """
            DELETE FROM ir_model_data
             WHERE module = 'base' AND model = 'ir.module.module' AND name = %s
            """,
            (f"module_{new}",),
        )
        _logger.info("Removed uninstalled placeholder for %s and its xmlid", new)

    cr.execute("UPDATE ir_module_module SET name = %s WHERE name = %s", (new, old))
    _logger.info("Renamed ir_module_module: %s -> %s (%d rows)", old, new, cr.rowcount)

    cr.execute("UPDATE ir_model_data SET module = %s WHERE module = %s", (new, old))
    _logger.info(
        "Renamed ir_model_data module: %s -> %s (%d rows)", old, new, cr.rowcount
    )

    # Every module owns an xmlid of its own, `base.module_<name>`, created by
    # the module-list scan. Renaming the row without it leaves that xmlid
    # naming a module nobody can find, and the next scan creates a second one
    # for the new name pointing at the same row.
    cr.execute(
        """
        UPDATE ir_model_data SET name = %s
         WHERE module = 'base' AND model = 'ir.module.module' AND name = %s
        """,
        (f"module_{new}", f"module_{old}"),
    )
    _logger.info(
        "Renamed base.module_%s -> base.module_%s (%d rows)", old, new, cr.rowcount
    )

    cr.execute(
        "UPDATE ir_module_module_dependency SET name = %s WHERE name = %s", (new, old)
    )
    _logger.info(
        "Renamed ir_module_module_dependency: %s -> %s (%d rows)", old, new, cr.rowcount
    )
