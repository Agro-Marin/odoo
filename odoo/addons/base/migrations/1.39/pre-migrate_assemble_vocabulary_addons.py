import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

# 1.24 swept the assemble verbs out of the core package. It could not see the
# bundled addons, enterprise or agromarin: naming_vocabulary.classify() dropped
# build/make/compose/construct unless the name ended in a payload suffix, so the
# ratchet read 0 while twenty-one definitions wore one. The suffix now chooses
# the canonical (_prepare_ with it, _get_ without) instead of deciding whether
# the verb is reached at all, and these are the names that fell out.
#
# Two renames of that sweep are deliberately absent:
#
# * `make_key` -> `action_generate_key` on auth.passkey.key.create. 1.24 already
#   carries that exact pair for res.users.apikeys' twin, and the rewrite is by
#   name and not by model, so a stored call was rewritten then.
# * `_make_zip` -> `_get_zip_response`. mail's controller was renamed and
#   document's identically-named twin was not, so rewriting the name here would
#   redirect stored code that means the other one.
_RENAMES = (
    ("_build_conditions", "_get_conditions_clause"),
    ("_build_due_week_buckets", "_get_due_week_buckets"),
    ("_build_field_clause", "_get_field_clause"),
    ("_build_filename", "_get_filename"),
    ("_build_from", "_get_from_clause"),
    ("_build_group_by", "_get_group_by_clause"),
    ("_build_having", "_get_having_clause"),
    ("_build_order_by", "_get_order_by_clause"),
    ("_build_pdf", "_get_pdf"),
    ("_build_select", "_get_select_clause"),
    ("_build_sign_requests_action", "_get_sign_requests_action"),
    ("_build_where", "_get_where_clause"),
    ("_compose_lot_name", "_get_lot_name"),
    ("_gc_delete_old_done_activities", "_gc_remove_old_done_activities"),
    ("_gc_delete_old_overdue_activities", "_gc_remove_old_overdue_activities"),
    ("_make_access_error", "_prepare_access_error"),
    ("_make_undiscountable_filter", "_get_undiscountable_filter"),
    ("build_qr_code_base64", "prepare_qr_code_base64"),
    ("make_scss_customization", "update_scss_customization"),
    ("make_test_order", "action_place_test_order"),
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
                "base 1.39: rewrote %d method name(s) in %s.%s -- %s",
                len(moved),
                table,
                column,
                ", ".join(f"{name} x{count}" for name, count in sorted(moved.items())),
            )

        survivors = _survivors(cr, table, column)
        if survivors:
            _logger.warning(
                "base 1.39: %s.%s still names %d renamed method(s) that attribute"
                " access did not reach -- review these rows by hand, they will"
                " raise at runtime: %s",
                table,
                column,
                len(survivors),
                ", ".join(
                    f"{name} (ids {ids})" for name, ids in sorted(survivors.items())
                ),
            )
