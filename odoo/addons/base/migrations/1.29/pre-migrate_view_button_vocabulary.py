import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

_ARCH_RENAMES = (
    ("action_related_contact", "action_view_related_contact", ("res.users",)),
    ("action_related_contacts", "action_view_related_contacts", ("hr.employee",)),
    ("do_unreserve", "action_unreserve", ("stock.picking", "mrp.production")),
    ("launch_replenishment", "action_replenish", ("product.replenish",)),
    ("open_at_date", "action_view_products_at_date", ("stock.quantity.history",)),
    ("order_avbl", "action_order_available_quantity", ("stock.replenishment.option",)),
    (
        "process_cancel_backorder",
        "action_cancel_backorder",
        ("stock.backorder.confirmation",),
    ),
)

_PYTHON_RENAMES = (("do_unreserve", "action_unreserve"),)


def _rewrite_attribute(expr, old, new):
    return rf"""replace({expr}, 'name="{old}"', 'name="{new}"')"""


def _rewrite_xpath_predicate(expr, old, new):
    return rf"""replace({expr}, '@name=''{old}''', '@name=''{new}''')"""


def _rename_view_buttons(cr):
    moved = {}
    for old, new, models in _ARCH_RENAMES:
        rewritten = _rewrite_xpath_predicate(
            _rewrite_attribute("kv.value", old, new), old, new
        )
        cr.execute(
            f"""
            UPDATE ir_ui_view v
               SET arch_db = (
                     SELECT jsonb_object_agg(kv.key, {rewritten})
                       FROM jsonb_each_text(v.arch_db) kv
                   )
             WHERE v.model = ANY(%s)
               AND EXISTS (
                     SELECT 1 FROM jsonb_each_text(v.arch_db) kv
                      WHERE kv.value LIKE %s OR kv.value LIKE %s
                   )
            """,
            (list(models), f'%name="{old}"%', f"%@name='{old}'%"),
        )
        if cr.rowcount:
            moved[old] = cr.rowcount
    return moved


def _view_survivors(cr):
    found = {}
    for old, _new, _models in _ARCH_RENAMES:
        cr.execute(
            "SELECT id FROM ir_ui_view WHERE arch_db::text ~ %s ORDER BY id LIMIT 20",
            (rf"\m{old}\M",),
        )
        ids = [row[0] for row in cr.fetchall()]
        if ids:
            found[old] = ids
    return found


def _pattern(name):
    return r"\." + name + r"\M"


def _rewrite(cr, table, column):
    moved = {}
    for old, new in _PYTHON_RENAMES:
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
    for old, _new in _PYTHON_RENAMES:
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

    moved = _rename_view_buttons(cr)
    if moved:
        _logger.info(
            "base 1.29: repointed %d stored arch(s) -- %s",
            sum(moved.values()),
            ", ".join(f"{name} x{count}" for name, count in sorted(moved.items())),
        )

    survivors = _view_survivors(cr)
    if survivors:
        _logger.warning(
            "base 1.29: %d renamed button name(s) survive in stored archs that the"
            " scoped rewrite did not reach -- review these views by hand, they will"
            " raise on validation: %s",
            len(survivors),
            "; ".join(
                f"{name} in view(s) {', '.join(str(i) for i in ids)}"
                for name, ids in sorted(survivors.items())
            ),
        )

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
