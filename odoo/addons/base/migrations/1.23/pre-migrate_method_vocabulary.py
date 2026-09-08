import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

_RENAMES = (
    ("_assign_new", "_update_new"),
    ("_assign_protected", "_update_protected"),
    ("_assign_real", "_update_real"),
    ("_delete_old_sessions", "_remove_old_sessions"),
    ("_delete_sid", "_remove_sid"),
    ("_delete_sql", "_unlink_sql"),
    ("_delete_sql_clear_company_dependent", "_unlink_sql_clear_company_dependent"),
    ("_delete_sql_default_guard", "_unlink_sql_default_guard"),
    ("_delete_sql_restrict_guard", "_unlink_sql_restrict_guard"),
    ("_ensure_error_response", "_get_or_create_error_response"),
    ("_ensure_field_triggers", "_get_field_triggers"),
    ("_ensure_inside_mirror", "_check_inside_mirror"),
    ("_ensure_pgcrypto", "_install_pgcrypto"),
    ("_ensure_xml_ids", "_get_or_create_xml_ids"),
    ("_export_fetch_fields", "_export_prefetch_fields"),
    ("_export_fill_properties_cache", "_export_update_properties_cache"),
    ("_fetch_mails", "_poll_due_mailboxes"),
    ("_fetch_row", "_get_row"),
    ("_fetch_terms_rows", "_get_terms_rows"),
    ("_inject_export_xids", "_update_export_xids"),
    ("_inject_future_response", "_update_response_from_future"),
    ("_purge_stale_fail_dumps", "_remove_stale_fail_dumps"),
    ("_read_group_fill_results", "_read_group_expand_results"),
    ("_sorted_ensure_computed", "_sorted_load_fields"),
    ("_validate_borrowed_conn", "_check_borrowed_conn"),
    ("_validate_computed", "_check_computed"),
    ("_validate_created", "_check_created"),
    ("_validate_fields", "_check_fields"),
    ("_validate_properties_definition", "_check_properties_definition"),
    ("action_retrieve_max_email_size", "action_update_max_email_size"),
    ("delete_all", "remove_all"),
    ("delete_from_identifiers", "remove_from_identifiers"),
    ("delete_old_sessions", "remove_old_sessions"),
    ("delete_rows", "remove_rows"),
    ("ensure_access", "check_read_access"),
    ("ensure_computed", "recompute_pending"),
    ("ensure_connectable", "check_connectable"),
    ("ensure_one", "check_singleton"),
    ("fetch_rows", "get_row_tuples"),
    ("fill_spec", "update_spec"),
    ("validate_csrf", "is_valid_csrf"),
    ("validate_custom_views", "check_custom_views"),
    ("verify_admin_password", "is_valid_admin_password"),
    ("verify_and_update", "match_and_update"),
)


def _pattern(name):
    return r"\." + name + r"\M"


def _rewrite(cr, table, column):
    moved = {}
    for old, new in _RENAMES:
        cr.execute(
            f"UPDATE {table} SET {column} ="
            f" regexp_replace({column}, %(pat)s, %(new)s, 'g')"
            f" WHERE {column} ~ %(pat)s",
            {"pat": _pattern(old), "new": "." + new},
        )
        if cr.rowcount:
            moved[old] = cr.rowcount
    return moved


def _survivors(cr, table, column):
    found = {}
    for old, _new in _RENAMES:
        cr.execute(
            f"SELECT id FROM {table} WHERE {column} ~ %s ORDER BY id LIMIT 20",
            (rf"(\.[[:space:]]+{old}\M)|(['\"]{old}['\"])",),
        )
        ids = [row[0] for row in cr.fetchall()]
        if ids:
            found[old] = ids
    return found


def migrate(cr, version):
    if not version:
        return

    for table, column in _STORED_PYTHON:
        if not schema.table_exists(cr, table):
            continue
        if not schema.column_exists(cr, table, column):
            continue

        moved = _rewrite(cr, table, column)
        if moved:
            _logger.info(
                "base 1.23: rewrote %d method name(s) in %s.%s -- %s",
                len(moved),
                table,
                column,
                ", ".join(f"{name} x{count}" for name, count in sorted(moved.items())),
            )

        survivors = _survivors(cr, table, column)
        if survivors:
            _logger.warning(
                "base 1.23: %s.%s still names %d renamed method(s) that attribute"
                " access did not reach -- review these rows by hand, they will"
                " raise AttributeError when they run: %s",
                table,
                column,
                len(survivors),
                "; ".join(
                    f"{name} in id(s) {', '.join(str(i) for i in ids)}"
                    for name, ids in sorted(survivors.items())
                ),
            )
