import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

_RENAMES = (
    ("_check_root_delegated_fields", "_check_delegated_fields_match_root"),
    ("_find_similar_named_partners", "_get_similar_named_partners"),
    ("_get_cached_template_prefetched_keys", "_get_field_names_in_cached_template"),
    ("_get_domain_context_values", "_get_context_values_in_domains"),
    ("_get_domain_keys", "_get_context_keys_in_domains"),
    ("_get_root_delegated_field_names", "_get_field_names_delegated_to_root"),
    ("_get_template_views", "_get_views_by_ref"),
    ("_load_certificate_material", "_read_certificate_material"),
    ("_set_identifier", "_update_identifier"),
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
