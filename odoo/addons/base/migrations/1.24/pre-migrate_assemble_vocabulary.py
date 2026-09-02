import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

# The sibling of base 1.23's rewrite, on the same three columns and for the same
# reason: source is rewritten by the ordinary upgrade, a database also holds
# Python in columns, and the ``_for_xml_id`` rename established both that this
# is a binding of the third kind and which columns hold it. What is new is the population -- the
# assemble verbs the ratchet could not see, §2.4.7.
_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

# METHODS ONLY, and the argument is 1.23's unchanged: stored Python runs under
# safe_eval with env / record / model in scope and no import, so a renamed
# module-level function (prepare_literal_eval, normalize_identifier,
# get_index_name and 15 more) is not reachable from it and rewriting its
# spelling could only ever hit a name belonging to somebody else.
#
# TWO EXCLUSIONS ARE NEW, AND BOTH ARE ABOUT THE OLD NAME RATHER THAN THE NEW.
# Seven of this sweep's definitions were spelled with a bare verb -- `make()`,
# `build()`, `_build()` -- and `.make` matches an attribute access on anybody's
# object, so those are left to the source rewrite alone. A nested closure
# (get_node_info, value_to_operand, get_column_type, add_term) is reachable by
# no attribute access at all and is excluded for the opposite reason: nothing
# outside its own function ever named it.
_RENAMES = (
    ("_build_cli", "_prepare_cli_parser"),
    ("_build_compile_request", "_prepare_compile_request"),
    ("_build_index_expression", "_get_index_expression"),
    ("_build_insert_rows", "_prepare_insert_rows"),
    ("_build_native_to_legacy_bridge", "_prepare_native_to_legacy_bridge"),
    ("_build_parent_self_bridge", "_prepare_parent_self_bridge"),
    ("_build_selection_index", "_prepare_selection_index_and_labels"),
    ("_build_watcher", "_arm_watcher"),
    ("_make_corecords", "_prepare_corecords"),
    ("_make_esbuild_compiler", "_prepare_esbuild_compiler"),
    ("build_shim_sources", "prepare_shim_sources"),
    ("check_access_make_key", "check_access_generate_key"),
    ("make_alias", "get_table_alias"),
    ("make_json_response", "prepare_json_response"),
    ("make_key", "action_generate_key"),
    ("make_response", "prepare_response"),
    ("make_xml_id", "normalize_xml_id"),
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

    The same two 1.23 reports, for the same reasons: Python accepts whitespace
    around the dot, and a name can be reached through getattr with a string
    literal. A bare occurrence is not one of them -- `make_key = 1` is the
    author's own local and the rewrite leaves it alone on purpose.
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
                "base 1.24: rewrote %d method name(s) in %s.%s -- %s",
                len(moved),
                table,
                column,
                ", ".join(f"{name} x{count}" for name, count in sorted(moved.items())),
            )

        survivors = _survivors(cr, table, column)
        if survivors:
            _logger.warning(
                "base 1.24: %s.%s still names %d renamed method(s) that attribute"
                " access did not reach -- review these rows by hand, they will"
                " raise at runtime: %s",
                table,
                column,
                len(survivors),
                ", ".join(
                    f"{name} (ids {ids})" for name, ids in sorted(survivors.items())
                ),
            )
