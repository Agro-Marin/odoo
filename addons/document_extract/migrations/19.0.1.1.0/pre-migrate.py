import logging

_logger = logging.getLogger(__name__)

#: States a row under the *new* name can be in and still be a placeholder the
#: module-list scan created rather than a module carrying data. `uninstalled` is
#: what the scan writes; `to install` is that same row one step further on,
#: promoted by dependency resolution because an installed module already lists
#: the new name in its `depends`. Neither holds anything to lose.
_PLACEHOLDER_STATES = ("uninstalled", "to install")

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
    cr.execute(
        "SELECT id, state, db_version FROM ir_module_module WHERE name = %s", (old,)
    )
    old_row = cr.fetchone()
    if not old_row:
        return
    old_id = old_row[0]

    # A module-list update runs before migrations and creates a row for every
    # module it finds on disk, so the new name is normally already there. See
    # `_PLACEHOLDER_STATES` for the two shapes that row takes. Any other state
    # means a real module carrying data, and merging onto it would lose one of
    # the two. Say so and leave both alone.
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

    # Everything the old module owns answers to the new name from here on. This
    # runs before either row is touched, so it is the same work in both branches.
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
    """Carry the old row onto the new name; nothing else claims it."""
    cr.execute("UPDATE ir_module_module SET name = %s WHERE id = %s", (new, old_id))
    _logger.info("Renamed ir_module_module: %s -> %s (id %s)", old, new, old_id)

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
    _logger.info("Renamed base.module_%s -> base.module_%s", old, new)


def _adopt_placeholder(cr, old, new, old_row, existing):
    """Keep the placeholder's row and give it the old module's history.

    The obvious move -- drop the placeholder, rename the old row onto the free
    name -- is wrong once the placeholder is `to install`: it is already a node
    in the module graph this upgrade is walking, and `load_data_and_demo`
    browses it by id. Deleting it raises `MissingError: Record does not exist`
    when the loader reaches that node, which takes the registry down as surely
    as the collision this guard was written to avoid.

    So the placeholder's id survives and inherits `state` and `db_version`, and
    the *old* row is the one dropped: its code is gone from disk, so the graph
    skipped it and nothing will browse it. Its xmlid goes with it -- the
    placeholder already has its own `base.module_<new>` from the scan.
    """
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
