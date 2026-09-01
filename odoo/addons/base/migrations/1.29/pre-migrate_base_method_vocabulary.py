import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

# The §2.4 sweep of `addons/base`. Source is rewritten by the ordinary upgrade;
# a database also holds Python in columns, and ADR-0056 established both that
# this is a binding of the third kind and which columns hold it. The shape, the
# anchoring and the survivor report are 1.23's, which swept core -- read that
# script first, this one only carries a different list. It sits beside
# pre-migrate_db_method_vocabulary.py in this version directory because the two
# sweeps landed in the same cycle and one upgrade step should carry both.
_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

# METHODS ONLY, and DISTINCTIVE ones -- 1.23's rule and 1.29's, both of which
# these six pass and a seventh does not.
#
# Every name below is a method on a model (`ir.rule`, `ir.ui.view`,
# `res.company`), so stored Python can reach it: it runs under safe_eval with
# env / record / model in scope and no import, and attribute access is the one
# route in. That is why each pattern is anchored on a leading dot.
#
# Two of the sweep's renames are NOT here, each excluded by one of the rules.
#
# `get_missing_fields` -> `get_fields_missing` is excluded by both at once. It
# is a method on `NameManager`, a plain helper class in
# ir_ui_view_name_manager.py rather than a model, and stored Python is handed
# env, record and model -- never a view's name manager -- so no server action
# can hold the receiver. It is also generic: `.get_missing_fields` on somebody
# else's object is likelier than on ours.
#
# `_find_duplicate` -> `_get_duplicate` is excluded by 1.23's rule alone. It is
# a module-level function in res_partner.py, and safe_eval offers no import, so
# no stored Python can reach it under either spelling.
#
# What remains is nine model methods, each naming something only `ir.rule`,
# `ir.ui.view`, `res.company`, `res.partner` or `ir.mail_server` has, so the
# corruption risk a bare `.collect` or `.age` would carry does not arise.
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
    """Rows still reaching an old method by a route the rewrite cannot take.

    1.23's two, for its reasons: Python accepts whitespace around the dot, and a
    name can be reached through getattr with a string literal. A bare occurrence
    is not reported -- it is the author's own local, and leaving it alone is the
    point of the dot anchor.

    `_get_domain_keys` is the one worth reading a report for. It is an extension
    point `website` already overrides, so it is the likeliest of the six to have
    been written down in a customer's stored Python.
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
