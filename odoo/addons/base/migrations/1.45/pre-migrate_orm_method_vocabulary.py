import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

# BaseModel methods renamed for §2.4 in odoo/orm (2026-09-10): the traversal
# and display-name helpers gain their verb, the parent-store and transient
# families lead with the verb their body performs, and the field-parameter
# hook takes the predicate prefix. Only the names a stored block can reach by
# attribute access on a record are listed; the cache and compute internals
# renamed in the same sweep are reached through env._core and are not.
_RENAMES = (
    ("_ancestor_ids", "_get_ancestor_ids"),
    ("_ancestor_ids_by_walking", "_get_ancestor_ids_by_walking"),
    ("_descendant_ids", "_get_descendant_ids"),
    ("_root", "_get_root"),
    ("_rec_name_fallback", "_get_rec_name_fallback"),
    ("_rec_names_search_field", "_get_rec_names_search_field"),
    ("_valid_field_parameter", "_is_valid_field_parameter"),
    ("_table_has_rows", "_has_rows_in_table"),
    ("_clean_properties", "_remove_stale_properties"),
    ("_invalid_load_paths", "_get_invalid_load_paths"),
    ("_parent_store_create", "_update_parent_path_on_create"),
    ("_parent_store_compute", "_update_parent_path_of_table"),
    ("_parent_store_update", "_update_parent_path_on_write"),
    ("_parent_store_update_prepare", "_get_records_with_parent_changed"),
    ("_transient_vacuum", "_vacuum_transient_rows"),
    ("_transient_clean_old_rows", "_remove_transient_rows_over_count"),
    ("_transient_clean_rows_older_than", "_remove_transient_rows_older_than"),
    (
        "_additional_allowed_keys_properties_definition",
        "_get_additional_allowed_keys_properties_definition",
    ),
)


def _pattern(name):
    return r"\." + name + r"\M"


def migrate(cr, version):
    if not version:
        return
    for table, column in _STORED_PYTHON:
        if not schema.table_exists(cr, table) or not schema.column_exists(
            cr, table, column
        ):
            continue
        for old, new in _RENAMES:
            cr.execute(
                f"UPDATE {table} SET {column} ="
                f" regexp_replace({column}, %(pat)s, %(new)s, 'g')"
                f" WHERE {column} ~ %(pat)s",
                {"pat": _pattern(old), "new": "." + new},
            )
            if cr.rowcount:
                _logger.info(
                    "base 1.45: %s.%s %s -> %s (%d row(s))",
                    table,
                    column,
                    old,
                    new,
                    cr.rowcount,
                )
