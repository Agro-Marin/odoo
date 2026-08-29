import logging

_logger = logging.getLogger(__name__)

_MODULE_RENAMES = {
    "base_account": "account_coa",
}


def _rename_modules(cr):
    renamed = 0
    adopted = 0
    for old, new in _MODULE_RENAMES.items():
        cr.execute(
            "DELETE FROM ir_module_module WHERE name = %s"
            " AND EXISTS (SELECT 1 FROM ir_module_module WHERE name = %s)",
            (old, new),
        )
        cr.execute("UPDATE ir_module_module SET name = %s WHERE name = %s", (new, old))
        renamed += cr.rowcount

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

    return renamed, adopted


def _reset_data_file_checksums(cr):
    cr.execute(
        "UPDATE ir_module_module SET data_file_checksums = NULL"
        " WHERE name = ANY(%s) AND data_file_checksums IS NOT NULL",
        (list(_MODULE_RENAMES.values()),),
    )
    return cr.rowcount


def _survivors(cr):
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
        "base 1.21: renamed %s module(s) %s, carrying over %s external "
        "identifier(s) and dropping the data-file xmlid cache of %s module(s)",
        renamed,
        ", ".join(f"{o} -> {n}" for o, n in _MODULE_RENAMES.items()),
        adopted,
        checksums,
    )

    survivors = _survivors(cr)
    if survivors:
        _logger.warning(
            "base 1.21: the rename left the old names behind in %s -- the map in "
            "this script is incomplete and those rows will resolve to nothing",
            ", ".join(survivors),
        )
