import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_MODULE_RENAMES = {
    "base_automation": "automation",
    "test_base_automation": "test_automation",
    "base_automation_hr": "automation_hr",
}

_MODEL_RENAMES = {
    "base.automation": "automation.rule",
    "base.automation.lead.test": "automation.lead.test",
    "base.automation.lead.thread.test": "automation.lead.thread.test",
    "base.automation.line.test": "automation.line.test",
    "base.automation.link.test": "automation.link.test",
    "base.automation.linked.test": "automation.linked.test",
    "base.automation.model.with.recname.char": "automation.model.with.recname.char",
    "base.automation.model.with.recname.m2o": "automation.model.with.recname.m2o",
    "test_base_automation.project": "test_automation.project",
    "test_base_automation.stage": "test_automation.stage",
    "test_base_automation.tag": "test_automation.tag",
    "test_base_automation.task": "test_automation.task",
}

_USAGE_RENAME = ("base_automation", "automation")

_MODEL_COLUMN_NAMES = (
    "model",
    "res_model",
    "src_model",
    "model_name",
    "relation",
    "resource",
    "model_id",
    "mail_model",
    "alias_model",
)

_MODEL_XMLID_PREFIXES = ("field_%s__", "constraint_%s_", "selection__%s__")


def _underscored(model):
    return model.replace(".", "_")


def _substituter(mapping):
    ordered = sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True)

    def substitute(text):
        for old, new in ordered:
            text = text.replace(old, new)
        return text

    return substitute


_SCHEMA_SUBSTITUTE = _substituter(
    {_underscored(old): _underscored(new) for old, new in _MODEL_RENAMES.items()}
)

_TEXT_SUBSTITUTE = _substituter(
    {
        **_MODEL_RENAMES,
        **_MODULE_RENAMES,
        "base_automation_id": "automation_rule_id",
    }
)


def _table_renames(cr):
    substitute = _SCHEMA_SUBSTITUTE
    cr.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
        " AND (tablename LIKE %s OR tablename LIKE %s)",
        (r"base\_automation%", r"%test\_base\_automation%"),
    )
    renames = {}
    for (table,) in cr.fetchall():
        new = substitute(table)
        if new != table and not schema.table_exists(cr, new):
            renames[table] = new
    return renames


def _rename_modules(cr):
    renamed = 0
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
    return renamed


def _rename_model_xmlids(cr):
    models = sorted(_MODEL_RENAMES.items(), key=lambda kv: len(kv[0]), reverse=True)
    moved = 0
    for old_model, new_model in models:
        old_us, new_us = _underscored(old_model), _underscored(new_model)
        cr.execute(
            "UPDATE ir_model_data SET name = %s WHERE model = 'ir.model' AND name = %s",
            (f"model_{new_us}", f"model_{old_us}"),
        )
        moved += cr.rowcount
        for template in (*_MODEL_XMLID_PREFIXES, "model_inherit__%s__"):
            old_prefix = template % old_us
            new_prefix = template % new_us
            cr.execute(
                "UPDATE ir_model_data SET name = %s || substring(name from %s)"
                " WHERE name LIKE %s",
                (new_prefix, len(old_prefix) + 1, old_prefix.replace("_", r"\_") + "%"),
            )
            moved += cr.rowcount

    substitute = _substituter(_MODULE_RENAMES)
    cr.execute(
        "SELECT id, name FROM ir_model_data WHERE name LIKE %s OR name LIKE %s",
        (r"%base\_automation%", r"%test\_base\_automation%"),
    )
    for data_id, name in cr.fetchall():
        cr.execute(
            "UPDATE ir_model_data SET name = %s WHERE id = %s",
            (substitute(name), data_id),
        )
        moved += 1
    return moved


def _rename_models(cr):
    substitute_tables = _SCHEMA_SUBSTITUTE
    updated = 0
    for old_model, new_model in _MODEL_RENAMES.items():
        cr.execute(
            "UPDATE ir_model SET model = %s WHERE model = %s", (new_model, old_model)
        )
        updated += cr.rowcount
        cr.execute(
            "UPDATE ir_model_fields SET model = %s WHERE model = %s",
            (new_model, old_model),
        )
        cr.execute(
            "UPDATE ir_model_fields SET relation = %s WHERE relation = %s",
            (new_model, old_model),
        )

    text_columns = (
        "name",
        "relation_table",
        "column1",
        "column2",
        "related",
        "relation_field",
    )
    for column in text_columns:
        cr.execute(
            f"SELECT id, {column} FROM ir_model_fields"
            f" WHERE {column} IS NOT NULL AND {column} LIKE %s",
            (r"%base\_automation%",),
        )
        for field_id, value in cr.fetchall():
            new = substitute_tables(value)
            if new != value:
                cr.execute(
                    f"UPDATE ir_model_fields SET {column} = %s WHERE id = %s",
                    (new, field_id),
                )

    for table, column in _model_bearing_columns(cr):
        for old_model, new_model in _MODEL_RENAMES.items():
            cr.execute(
                f'UPDATE "{table}" SET "{column}" = %s WHERE "{column}" = %s',
                (new_model, old_model),
            )
    return updated


def _model_bearing_columns(cr):
    cr.execute(
        """
        SELECT c.table_name, c.column_name
          FROM information_schema.columns c
          JOIN information_schema.tables t
            ON t.table_schema = c.table_schema AND t.table_name = c.table_name
         WHERE c.table_schema = current_schema()
           AND t.table_type = 'BASE TABLE'
           AND c.data_type IN ('character varying', 'text')
           AND c.column_name = ANY(%s)
        """,
        (list(_MODEL_COLUMN_NAMES),),
    )
    return cr.fetchall()


def _rename_tables(cr, table_renames):
    substitute = _substituter(table_renames)

    cr.execute(
        """
        SELECT table_name, column_name FROM information_schema.columns
         WHERE table_schema = current_schema() AND column_name LIKE %s
        """,
        (r"%base\_automation%\_id",),
    )
    for table, column in cr.fetchall():
        new = substitute(column)
        if new != column and not schema.column_exists(cr, table, new):
            cr.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{column}" TO "{new}"')

    for old, new in sorted(table_renames.items()):
        if not schema.table_exists(cr, old):
            continue
        cr.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')
        cr.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass", (new,)
        )
        for (name,) in cr.fetchall():
            renamed = substitute(name)
            if renamed != name:
                cr.execute(
                    f'ALTER TABLE "{new}" RENAME CONSTRAINT "{name}" TO "{renamed}"'
                )
        cr.execute(
            "SELECT indexname FROM pg_indexes"
            " WHERE schemaname = current_schema() AND tablename = %s",
            (new,),
        )
        for (name,) in cr.fetchall():
            renamed = substitute(name)
            if renamed != name and not schema.index_exists(cr, renamed):
                cr.execute(f'ALTER INDEX "{name}" RENAME TO "{renamed}"')

    for table, column in (
        ("ir_model_constraint", "name"),
        ("ir_model_relation", "name"),
    ):
        cr.execute(
            f"SELECT id, {column} FROM {table} WHERE {column} LIKE %s",
            (r"%base\_automation%",),
        )
        for row_id, value in cr.fetchall():
            cr.execute(
                f"UPDATE {table} SET {column} = %s WHERE id = %s",
                (substitute(value), row_id),
            )
    return len(table_renames)


def _sweep_source_text(cr):
    substitute = _TEXT_SUBSTITUTE
    columns = (
        ("ir_ui_view", "arch_db", True),
        ("ir_ui_view", "arch_prev", False),
        ("ir_ui_view", "arch_fs", False),
        ("ir_ui_view", "name", False),
        ("ir_act_server", "code", False),
        ("ir_rule", "domain_force", False),
        ("ir_filters", "domain", False),
        ("ir_filters", "context", False),
        ("ir_act_window", "domain", False),
        ("ir_act_window", "context", False),
    )
    rewritten = 0
    for table, column, is_jsonb in columns:
        if not schema.column_exists(cr, table, column):
            continue
        cast = "::text" if is_jsonb else ""
        cr.execute(
            f"SELECT id, {column}{cast} FROM {table}"
            f" WHERE {column}{cast} ~ 'base[._]automation'"
        )
        for row_id, value in cr.fetchall():
            new = substitute(value)
            if new == value:
                continue
            back = "::jsonb" if is_jsonb else ""
            cr.execute(
                f"UPDATE {table} SET {column} = %s{back} WHERE id = %s", (new, row_id)
            )
            rewritten += 1
    return rewritten


def _reset_data_file_checksums(cr):
    cr.execute(
        "UPDATE ir_module_module SET data_file_checksums = NULL"
        " WHERE name = ANY(%s) AND data_file_checksums IS NOT NULL",
        (list(_MODULE_RENAMES.values()),),
    )
    return cr.rowcount


def _rename_server_action_usage(cr):
    old, new = _USAGE_RENAME
    if not schema.column_exists(cr, "ir_act_server", "usage"):
        return 0
    cr.execute("UPDATE ir_act_server SET usage = %s WHERE usage = %s", (new, old))
    actions = cr.rowcount
    cr.execute(
        """
        UPDATE ir_model_fields_selection s SET value = %s
          FROM ir_model_fields f
         WHERE f.id = s.field_id
           AND f.model = 'ir.actions.server' AND f.name = 'usage'
           AND s.value = %s
        """,
        (new, old),
    )
    return actions


def _survivors(cr):
    checks = (
        ("ir_module_module", "name"),
        ("ir_module_module_dependency", "name"),
        ("ir_model_data", "module"),
        ("ir_model_data", "name"),
        ("ir_model", "model"),
        ("ir_model_fields", "model"),
        ("ir_model_fields", "relation"),
        ("ir_model_fields", "relation_table"),
        ("ir_ui_view", "arch_db::text"),
        ("ir_act_server", "code"),
        ("ir_rule", "domain_force"),
    )
    found = []
    for table, column in checks:
        cr.execute(
            f"SELECT count(*) FROM {table} WHERE {column} ~ 'base[._]automation'"
        )
        (count,) = cr.fetchone()
        if count:
            found.append(f"{table}.{column}={count}")
    return found


def migrate(cr, version):
    if not version:
        return

    table_renames = _table_renames(cr)
    modules = _rename_modules(cr)
    xmlids = _rename_model_xmlids(cr)
    models = _rename_models(cr)
    tables = _rename_tables(cr, table_renames)
    actions = _rename_server_action_usage(cr)
    quoted = _sweep_source_text(cr)
    checksums = _reset_data_file_checksums(cr)

    _logger.info(
        "base 1.17: renamed %s module(s) %s, %s model(s), %s table(s), %s xmlid(s), "
        "%s server action(s) off the base_automation usage value, rewrote %s "
        "row(s) of stored source quoting the old names, and dropped the data-file "
        "xmlid cache of %s module(s)",
        modules,
        ", ".join(f"{o} -> {n}" for o, n in _MODULE_RENAMES.items()),
        models,
        tables,
        xmlids,
        actions,
        quoted,
        checksums,
    )

    survivors = _survivors(cr)
    if survivors:
        _logger.warning(
            "base 1.17: the rename left base_automation behind in %s -- the map in "
            "this script is incomplete and those rows will resolve to nothing",
            ", ".join(survivors),
        )
