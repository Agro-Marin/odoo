import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

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
