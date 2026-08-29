import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_OLD_MODULE = "base_sql_report"
_NEW_MODULE = "mixin_report_sql"

_MODEL_RENAMES = (
    ("base.sql.report.test.source", "mixin.report.sql.test.source"),
    ("base.sql.report.test.plain", "mixin.report.sql.test.plain"),
    ("base.sql.report.test.mv", "mixin.report.sql.test.mv"),
    ("base.sql.report.test.rolling", "mixin.report.sql.test.rolling"),
)

_TABLE_RENAMES = tuple(
    (old.replace(".", "_"), new.replace(".", "_")) for old, new in _MODEL_RENAMES
)

_XMLID_PREFIX_RENAMES = tuple(
    prefix
    for old_table, new_table in _TABLE_RENAMES
    for prefix in (
        (f"model_{old_table}", f"model_{new_table}"),
        (f"field_{old_table}__", f"field_{new_table}__"),
    )
)


def _module_row_id(cr):
    cr.execute("SELECT id FROM ir_module_module WHERE name = %s", (_OLD_MODULE,))
    row = cr.fetchone()
    return row[0] if row else None


def _rename_module(cr, module_id):
    cr.execute(
        "UPDATE ir_module_module SET name = %s WHERE id = %s",
        (_NEW_MODULE, module_id),
    )
    for table in ("ir_module_module_dependency", "ir_module_module_exclusion"):
        cr.execute(
            f"DELETE FROM {table} d WHERE d.name = %s"
            f" AND EXISTS (SELECT 1 FROM {table} o"
            f"              WHERE o.name = %s AND o.module_id = d.module_id)",
            (_OLD_MODULE, _NEW_MODULE),
        )
        cr.execute(
            f"UPDATE {table} SET name = %s WHERE name = %s",
            (_NEW_MODULE, _OLD_MODULE),
        )
    cr.execute(
        "SELECT count(*) FROM ir_module_module_dependency WHERE name = %s",
        (_NEW_MODULE,),
    )
    (dependents,) = cr.fetchone()

    cr.execute(
        "DELETE FROM ir_model_data WHERE module = 'base' AND name = %s"
        " AND EXISTS (SELECT 1 FROM ir_model_data"
        "              WHERE module = 'base' AND name = %s)",
        (f"module_{_OLD_MODULE}", f"module_{_NEW_MODULE}"),
    )
    cr.execute(
        "UPDATE ir_model_data SET name = %s"
        " WHERE module = 'base' AND model = 'ir.module.module' AND name = %s",
        (f"module_{_NEW_MODULE}", f"module_{_OLD_MODULE}"),
    )
    cr.execute(
        "UPDATE ir_model_data SET module = %s WHERE module = %s",
        (_NEW_MODULE, _OLD_MODULE),
    )
    owned = cr.rowcount
    cr.execute(
        "UPDATE ir_module_module SET data_file_checksums = NULL WHERE id = %s",
        (module_id,),
    )
    return dependents, owned


def _rename_models(cr):
    renamed = []
    for old_model, new_model in _MODEL_RENAMES:
        cr.execute(
            "UPDATE ir_model SET model = %s WHERE model = %s", (new_model, old_model)
        )
        if not cr.rowcount:
            continue
        cr.execute(
            "UPDATE ir_model_fields SET model = %s WHERE model = %s",
            (new_model, old_model),
        )
        cr.execute(
            "UPDATE ir_model_fields SET relation = %s WHERE relation = %s",
            (new_model, old_model),
        )
        cr.execute(
            "UPDATE ir_model_data SET model = %s WHERE model = %s",
            (new_model, old_model),
        )
        cr.execute(
            "UPDATE ir_ui_view SET model = %s WHERE model = %s",
            (new_model, old_model),
        )
        renamed.append(f"{old_model} -> {new_model}")
    return renamed


def _rename_owned_relations(cr, old_table, new_table):
    # ALTER ... RENAME leaves indexes, sequences and constraints under the old
    # name. mixin.materialized.view derives every index name from _table and
    # creates it IF NOT EXISTS, so an index left behind is not cosmetic: it
    # becomes a second, permanently unmaintained copy the next init() cannot see.
    cr.execute(
        """
        SELECT c.relname, c.relkind FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = current_schema()
           AND c.relkind IN ('i', 'S')
           AND c.relname LIKE %s
        """,
        (f"{old_table}%",),
    )
    for relname, relkind in cr.fetchall():
        target = f"{new_table}{relname[len(old_table) :]}"
        keyword = "INDEX" if relkind == "i" else "SEQUENCE"
        cr.execute(f'ALTER {keyword} "{relname}" RENAME TO "{target}"')

    cr.execute(
        "SELECT conname FROM pg_constraint"
        " WHERE conrelid = %s::regclass AND conname LIKE %s",
        (new_table, f"{old_table}%"),
    )
    for (conname,) in cr.fetchall():
        new_conname = f"{new_table}{conname[len(old_table) :]}"
        cr.execute(
            f'ALTER TABLE "{new_table}" RENAME CONSTRAINT "{conname}"'
            f' TO "{new_conname}"'
        )
        cr.execute(
            "UPDATE ir_model_constraint SET name = %s WHERE name = %s",
            (new_conname, conname),
        )


def _relation_kind(cr, relname):
    cr.execute(
        "SELECT c.relkind FROM pg_class c JOIN pg_namespace n"
        " ON n.oid = c.relnamespace"
        " WHERE n.nspname = current_schema() AND c.relname = %s",
        (relname,),
    )
    row = cr.fetchone()
    return row[0] if row else None


def _rename_tables(cr):
    renamed = []
    for old_table, new_table in _TABLE_RENAMES:
        kind = _relation_kind(cr, old_table)
        if kind is None:
            continue
        if _relation_kind(cr, new_table) is not None:
            _logger.warning(
                "base 1.20: %s and %s both exist, leaving them alone",
                old_table,
                new_table,
            )
            continue
        keyword = "MATERIALIZED VIEW" if kind == "m" else "TABLE"
        cr.execute(f'ALTER {keyword} "{old_table}" RENAME TO "{new_table}"')
        _rename_owned_relations(cr, old_table, new_table)
        renamed.append(f"{old_table} -> {new_table}")
    return renamed


def _rename_xmlids(cr):
    renamed = 0
    for old_prefix, new_prefix in _XMLID_PREFIX_RENAMES:
        cr.execute(
            """
            UPDATE ir_model_data
               SET name = %s || substring(name from %s)
             WHERE module = %s AND name LIKE %s
            """,
            (new_prefix, len(old_prefix) + 1, _NEW_MODULE, f"{old_prefix}%"),
        )
        renamed += cr.rowcount
    return renamed


def _rename_config_parameters(cr):
    renamed = []
    for old_model, new_model in _MODEL_RENAMES:
        cr.execute(
            """
            UPDATE ir_config_parameter
               SET key = %s || substring(key from %s)
             WHERE key LIKE %s
         RETURNING key
            """,
            (new_model, len(old_model) + 1, f"{old_model}.%"),
        )
        renamed.extend(row[0] for row in cr.fetchall())
    return renamed


def _survivors(cr):
    found = []
    for table, column, values in (
        ("ir_module_module", "name", [_OLD_MODULE]),
        ("ir_module_module_dependency", "name", [_OLD_MODULE]),
        ("ir_module_module_exclusion", "name", [_OLD_MODULE]),
        ("ir_model_data", "module", [_OLD_MODULE]),
        ("ir_model", "model", [old for old, _ in _MODEL_RENAMES]),
        ("ir_model_fields", "model", [old for old, _ in _MODEL_RENAMES]),
        ("ir_model_data", "model", [old for old, _ in _MODEL_RENAMES]),
        ("ir_ui_view", "model", [old for old, _ in _MODEL_RENAMES]),
    ):
        cr.execute(f"SELECT count(*) FROM {table} WHERE {column} = ANY(%s)", (values,))
        (count,) = cr.fetchone()
        if count:
            found.append(f"{table}.{column}={count}")

    cr.execute(
        "SELECT count(*) FROM ir_model_data WHERE module = 'base' AND name = %s",
        (f"module_{_OLD_MODULE}",),
    )
    (count,) = cr.fetchone()
    if count:
        found.append(f"ir_model_data.base.module_{_OLD_MODULE}={count}")

    for old_table, _new_table in _TABLE_RENAMES:
        if schema.table_exists(cr, old_table):
            found.append(f"relation {old_table}")
    return found


def migrate(cr, version):
    if not version:
        return
    module_id = _module_row_id(cr)
    if module_id is None:
        return

    dependents, owned = _rename_module(cr, module_id)
    models = _rename_models(cr)
    tables = _rename_tables(cr)
    xmlids = _rename_xmlids(cr)
    parameters = _rename_config_parameters(cr)

    _logger.info(
        "base 1.20: renamed module %s -> %s (%d dependency row(s), %d owned "
        "external identifier(s)), %d model(s) %s, %d relation(s) %s, "
        "%d model and field xmlid(s), %d config parameter(s) %s",
        _OLD_MODULE,
        _NEW_MODULE,
        dependents,
        owned,
        len(models),
        ", ".join(models),
        len(tables),
        ", ".join(tables),
        xmlids,
        len(parameters),
        ", ".join(parameters),
    )

    survivors = _survivors(cr)
    if survivors:
        _logger.warning(
            "base 1.20: the rename left the old names behind in %s -- the maps "
            "in this script are incomplete and those rows will resolve to nothing",
            ", ".join(survivors),
        )
