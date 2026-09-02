import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

# The §2.4 sweep of the core `db` package. Source is rewritten by the ordinary
# upgrade; a database also holds Python in columns, and the ``_for_xml_id``
# rename established both that this is a binding of the third kind and which
# columns hold it. The
# shape, the anchoring and the survivor report are 1.23's, which swept the rest
# of core -- read that script first, this one only carries a different list.
_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

# METHODS ONLY, and DISTINCTIVE ones, which is the whole of the safety argument.
# 1.23 made the first half: stored Python runs under safe_eval with no import,
# so a module-level function is not reachable from it and rewriting its spelling
# could only hit a name belonging to somebody else. That excludes most of this
# sweep on its own -- `schema.get_tables_existing`, `utils.get_connection_info_
# for_database`, `savepoint.get_or_create_row`, `probe.get_libpq_connect_
# timeout`, `errors.has_reached_server` and the rest are module-level and are
# not here.
#
# The second half is new, and it is the reason this list is shorter than the
# sweep. A leading dot proves attribute access; it does not prove WHOSE
# attribute. `.snapshot`, `.health`, `.age`, `.due`, `.collect`, `.allow`,
# `.allows`, `.outstanding` and `._format` were all renamed in `odoo/db` and
# none is here: every one of them is a plausible member of a model an author
# wrote themselves, so a dot-anchored rewrite would corrupt working code to fix
# a call nobody makes. A pool internal reached from a server action is already
# a stretch; trading a real corruption for a hypothetical AttributeError is not
# the trade. Where the generic name is the only route to an object, the object
# is `env.cr`'s pool, which stored Python has no business holding.
#
# The second §2.4 pass over the package adds five names and excludes four more
# under the two rules above, unchanged. Module-level, so out by the first half:
# `schema.drop_depending_views` -> `drop_views_depending_on_table` and
# `schema.get_constraint_columns` -> `get_column_names_in_constraint`. Too
# generic to anchor on a dot, so out by the second: `ConnectionPool.drain` ->
# `drain_all` and `ConnectionBudget.exhausted` -> `exhausted_count`. `.drain`
# and `.exhausted` are both plausible members of a model an author wrote --
# `.drain` doubly so, because psycopg_pool's own pool declares one, so a
# dot-anchored rewrite cannot tell the wrapper from the wrapped any better than
# a `sed` can.
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
    """Rows still reaching an old method by a route the rewrite cannot take.

    1.23's two: whitespace around the dot, and getattr with a string literal.
    Both are rare enough not to rewrite blind and too damaging to leave silent.
    A bare occurrence is not one of them and is not reported -- it is the
    author's own local, and these names are common enough as locals that the
    noise would bury the two real cases.
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
