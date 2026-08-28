"""Rename ``base_automation`` to ``automation``, and ``base.automation`` to ``automation.rule``.

Three modules change name -- ``base_automation`` -> ``automation``,
``test_base_automation`` -> ``test_automation``, ``base_automation_hr`` ->
``automation_hr`` -- and twelve models with them. On disk that is a directory
move; in a populated database it is nothing of the sort. The module name is the
namespace half of every xmlid the module owns, it is what
``ir_module_module_dependency`` names its dependents by, and the model name is
carried in `ir_model`, in every `ir_model_fields` row that points at it, and in
the ~30 columns elsewhere that store a model name as text.

**This has to run in base's own pre-migration, and cannot run in the renamed
modules' own.** A module's migration scripts are found through its manifest, and
after the rename there is no manifest at ``base_automation``: the loader reads
``ir_module_module`` for a module it cannot find on disk, logs *"Perhaps a module
was partially removed or renamed"*, and skips it -- migrations included. So the
only hook that fires is base's, which is also the first the loader reaches. Every
addon migration that runs afterwards therefore sees the **new** schema, which is
why ``automation``'s own 1.1 and 1.3 scripts were rewritten to speak it (each
says so in its docstring), and why ``api_stock_scale``'s 19.0.1.6.0 was too.

**It requires ``-u base``.** ``load_modules`` only marks base *to upgrade* when
it is named on the command line; a version bump alone does not do it. Upgrading
with anything narrower leaves ``base_automation`` installed, unfindable, and
still owning every record.

Ordering inside the script is not free either. ``ir_model_fields`` is renamed
before the tables it describes only because nothing reads it in between; the
tables are renamed before their constraints and indexes because
``ALTER TABLE ... RENAME`` carries neither.

The one entry here that is not a rename is ``ir_act_server.usage``. Its
``base_automation`` value comes from a ``selection_add`` whose ``ondelete`` is
``cascade``: left behind, the reflected model would find the value gone and
cascade -- deleting the server action of every automation rule in the database.

Idempotent, and resumable rather than all-or-nothing. Every statement is
guarded on the old name being present and, where a collision is possible, on the
new one being absent; there is deliberately no early return once the module rows
have moved. A run that renames the schema and then fails while the module data
reloads leaves a database whose modules are already ``automation`` but whose
view arch still quotes ``base_automation_id`` -- and an all-or-nothing guard
would decline to touch it on the next attempt, which is the one state where
finishing the job matters most.
"""

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

# The columns that hold a model name as text, found by name rather than listed:
# the set differs with which modules are installed, and a list written here
# would be a list of whichever ones happened to be installed when it was
# written. Restricted to these column names because a full scan would have to
# seq-scan every text column in the database -- mail_message.body included.
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

# ir_model_data.name shapes that are derived from the MODEL, and so follow the
# model rename rather than the module one. `%s` is the model with its dots
# turned into underscores. Everything else the module owns -- view, menu, cron,
# ACL and digest-tip xmlids -- carries the module name instead and is handled by
# the module substitution.
_MODEL_XMLID_PREFIXES = ("field_%s__", "constraint_%s_", "selection__%s__")


def _underscored(model):
    return model.replace(".", "_")


def _substituter(mapping):
    """Longest key first, so ``base_automation_lead_test`` is not eaten by ``base_automation``."""
    ordered = sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True)

    def substitute(text):
        for old, new in ordered:
            text = text.replace(old, new)
        return text

    return substitute


# Everything named after a model's *table*: the tables themselves, the many2many
# tables built from two of them, the ``<table>_id`` key columns, and the
# constraint and index names PostgreSQL derives from all of those.
_SCHEMA_SUBSTITUTE = _substituter(
    {_underscored(old): _underscored(new) for old, new in _MODEL_RENAMES.items()}
)

# Stored source -- view arch, server-action code, domains -- quotes models by
# their dotted name and modules by theirs, and the bare token ``base_automation``
# there is always the *module*: an ``arch_fs`` path, an xmlid prefix, the
# ``usage`` value. The one table-flavoured spelling that reaches this text is the
# many2one field Odoo names after the model, and its ``_id`` suffix is what
# tells the two apart -- so it is listed explicitly and, being longer, is matched
# first.
_TEXT_SUBSTITUTE = _substituter(
    {
        **_MODEL_RENAMES,
        **_MODULE_RENAMES,
        "base_automation_id": "automation_rule_id",
    }
)


def _table_renames(cr):
    """The tables still carrying an old name, mapped to the new one.

    Discovered rather than listed because the many2many tables are named after
    the two tables they join --
    ``base_automation_lead_test_test_base_automation_tag_rel`` carries two
    renamed names at once -- and because a resumed run must find only the ones
    that have not moved yet.
    """
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
        # A row under the new name can only exist if this already ran. (module,
        # name) and ir_module_module.name are both unique, so the stale row is
        # what has to go, not the live one.
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
    """Move the model-derived xmlids, then the module-derived ones.

    Order matters: ``field_base_automation__name`` has to be claimed by the model
    pass before the module pass, which would otherwise spell it
    ``field_automation__name`` and orphan the ``ir.model.fields`` row -- and an
    orphaned ``ir.model.fields`` row takes its column with it when it is reaped.
    Longest model first, so ``base.automation`` does not claim
    ``field_base_automation_lead_test__tag_ids``.
    """
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

    # ir_model_fields also carries the *table* vocabulary: the many2one field
    # named after the model (base_automation_id), the many2many join table and
    # its two key columns, and the related/relation_field paths spelled with them.
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
    """Rename the tables, their id columns wherever they are referenced, and the
    constraints and indexes PostgreSQL leaves behind under the old name."""
    substitute = _substituter(table_renames)

    # Columns first: a many2many key column is named after the table it points
    # at, which may be a different table from the one it lives in.
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
        # ALTER TABLE ... RENAME renames neither, and ir_model_constraint /
        # ir_model_relation are matched against them by name.
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
    """Rewrite the columns that *quote* a module, model or field name.

    These are not identity columns -- they are stored source: view arch, the
    Python of a server action, a rule's domain, a saved filter. They divide into
    three, and only two of the three are load-bearing.

    ``arch_db`` is, and measurably so. A view owned by a renamed module is
    rewritten from its file during this same upgrade, so leaving it stale looks
    harmless; it is not, because the loader validates each view *as it writes
    it*, against the views already in the table. A sibling still saying
    ``base_automation_id`` fails that validation before its own turn to be
    rewritten arrives -- ``Unknown field "ir.actions.server.base_automation_id"
    in domain of <field name="predecessor_ids">`` -- and the upgrade stops
    there, inside the very reload that would have fixed it.

    ``ir_act_server.code`` and the rule and filter domains are, by construction:
    no file derives them, so nothing ever rewrites them. A server action whose
    code reads ``env["base.automation"]`` is the administrator's own text and
    survives every upgrade, broken, until the moment someone runs it. Same
    category as the checksum cache above.

    ``arch_fs``, ``arch_prev`` and ``ir_ui_view.name`` are neither. They are
    rewritten whenever the module's data files are re-converted, which
    ``_reset_data_file_checksums`` guarantees. They are kept here as
    belt-and-braces -- one UPDATE over a handful of rows, and correct in the
    case where the module does not reload -- not because they were measured to
    be necessary. They were not.
    """
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
    """Drop the per-file xmlid cache of every renamed module.

    ``ir_module_module.data_file_checksums`` maps each data file to a content
    sha and the xmlids that file created -- **fully qualified**,
    ``f"{module}.{name}"`` (``ir_model_data.py``). A module rename changes no
    file's content, so the next upgrade finds every sha unchanged, takes the
    skip branch in ``load_data`` and seeds ``registry.loaded_xmlids`` from the
    cache: with ``base_automation.*``, while ``_process_end`` is building
    ``automation.*`` candidates from the rows this script just renamed. The two
    sets cannot intersect, so every non-``noupdate`` record the module owns --
    views, menus, actions, ACLs -- is reaped as stale. Silently: the deletions
    log at INFO and the upgrade exits 0.

    ``NULL`` is the spelling ``module_uninstall()`` already uses, and it costs
    one full data load of three modules, once.

    A fresh-install test cannot show this. ``track`` requires ``mode ==
    "update"``, so a module that has only ever been installed has no checksums
    to go stale -- which is why this needs a database that was *upgraded* at
    least once under the old name.
    """
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
    """Anything still spelling the old names in a table that keys on them.

    Reported rather than repaired: a leftover here means this script's map is
    incomplete, and a silent partial rename is the failure mode that produces a
    database whose xmlids resolve to nothing months later.
    """
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
