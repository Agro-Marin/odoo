import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

_RENAMES = (
    ("_binary_pays_off", "_is_binary_copy_worthwhile"),
    ("_borrow_direct", "_borrow_directly"),
    ("_budget_exhausted", "_prepare_budget_exhausted_error"),
    ("_check_borrowed_conn", "_check_borrowed_connection"),
    ("_close_each", "_close_pools"),
    ("_col_names", "_get_column_names"),
    ("_connection_is_clean", "_is_connection_clean"),
    ("_cooldown_remaining_locked", "_get_cooldown_remaining_locked"),
    ("_drain_each", "_drain_pools"),
    ("_for_database", "_get_keys_for_database"),
    ("_getconn_with_retry", "_get_connection_with_retry"),
    ("_maybe_reap_idle_pools", "_reap_idle_pools_if_due"),
    ("_reap_after_return", "_reap_idle_pools_safely"),
    ("_resolve_ddl", "_prepare_ddl_statement"),
    ("_resolve_id_sequence", "_get_id_sequence"),
    ("_safe_close", "_close_pool_safely"),
    ("_safe_drain", "_drain_pool_safely"),
    ("clear_catalog_facts", "invalidate_catalog_facts"),
    ("close_in_background", "close_pools_in_background"),
    ("database_absent", "is_database_absent"),
    ("discard_cached_plans", "invalidate_cached_plans"),
    ("due_for_report", "acquire_report_interval"),
    ("due_for_sample", "acquire_sample_interval"),
    ("forget_each", "forget_keys"),
    ("forget_matching", "forget_keys_matching"),
    ("get_budget_at", "get_budget_at_endpoint"),
    ("get_budget_for", "get_budget_for_readonly"),
    ("get_endpoint_of", "get_endpoint_for_readonly"),
    ("get_maxconn_at", "get_maxconn_at_endpoint"),
    ("get_maxconn_for", "get_maxconn_for_readonly"),
    ("get_pool_at", "get_pool_at_endpoint"),
    ("get_pool_for", "get_pool_for_readonly"),
    ("oldest_age", "get_oldest_age"),
    ("probably_due", "is_probably_due"),
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
                "base 1.29: rewrote %d method name(s) in %s.%s -- %s",
                len(moved),
                table,
                column,
                ", ".join(f"{name} x{count}" for name, count in sorted(moved.items())),
            )

        survivors = _survivors(cr, table, column)
        if survivors:
            _logger.warning(
                "base 1.29: %s.%s still names %d renamed method(s) that attribute"
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
