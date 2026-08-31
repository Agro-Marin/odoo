import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

# ADR-0078 renamed every abolished-verb definition in the core package. Source is
# rewritten by the ordinary upgrade; a database also holds Python in columns, and
# ADR-0056 established both that this is a binding of the third kind and which
# columns hold it.
_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

# METHODS ONLY, and that is the whole of the safety argument. Stored Python runs
# under safe_eval with env / record / model in scope and no import, so a renamed
# module-level function (validate_db_name, normalize_url, verify_hash_signed and
# 13 more) is not reachable from it and rewriting its spelling could only ever
# hit a name that belongs to somebody else. A method is reachable exactly one
# way -- attribute access -- which is why every pattern below is anchored on a
# leading dot rather than on a bare word boundary: `.delete_rows` is ours,
# `delete_rows` on its own is a local of the author's that we must not touch.
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
    """Rows still reaching an old method by a route the rewrite cannot take.

    Two of them, and deliberately not a third. Python accepts whitespace around
    the dot (`record . name()`, or a continuation across lines), and a name can
    be reached through getattr with a string literal. Both are rare enough not to
    rewrite blind and too damaging to leave silent.

    A BARE OCCURRENCE IS NOT ONE OF THEM. `delete_rows = 1` is the author's own
    local and the rewrite leaves it alone on purpose, so reporting it would ask
    an operator to review the one thing that is certainly correct -- and these
    names are common enough as locals (`delete_rows`, `make_key`, `update_spec`)
    that the noise would bury the two real cases.
    """
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
