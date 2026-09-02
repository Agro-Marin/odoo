import logging

from odoo.db import schema

_logger = logging.getLogger(__name__)

# The §2.4 sweep renamed object buttons as well as the methods behind them, and
# a button is bound from two places the ordinary upgrade does not reach in time.
#
# The stored arch is one. `-u all` does reload each module's XML, so every view
# below would eventually be rewritten from source -- but not before it is read.
# A parent view's reload revalidates every view inheriting it, and validation
# resolves `type="object"` button names against the model, so a downstream arch
# still naming the old method raises ParseError while its own module is still
# waiting its turn. `marin`'s stock.picking form is exactly that shape: it
# inherits `stock`'s, `stock` loads first, and the rename it carries in its own
# XML arrives too late to save the load. This is the failure that costs one
# `-u all` cycle per module when it is left to surface on its own; project 1.20
# is the same script for one button, and states the same reason.
#
# Stored Python is the other, and nothing rewrites it at all. Three server
# actions named "Unreserve" call `.do_unreserve()` on a recordset; the upgrade
# has no opinion about them and they raise AttributeError the first time an
# operator presses the button. `_STORED_PYTHON` and the dot-anchored pattern are
# 1.23's, which this file reuses rather than restates -- read that script first.
_STORED_PYTHON = (
    ("ir_act_server", "code"),
    ("ir_actions_server_history", "code"),
    ("ir_model_fields", "compute"),
)

# Buttons, scoped to the models that declare them. Scoping is 1.20's rule and it
# is what makes a whole-attribute-value rewrite safe: none of these seven names
# is a field (checked against `ir_model_fields` on marin190, 0 rows), so the only
# way to reach one is a button, and the model bound tells a button of ours from a
# same-named button of somebody else's.
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

# Only the one rename of the seven that stored Python can reach. The other six
# name wizard and report buttons whose receiver a server action is not handed,
# and 1.23's rule is not to rewrite a spelling nothing can be holding.
_PYTHON_RENAMES = (("do_unreserve", "action_unreserve"),)


def _rewrite_attribute(expr, old, new):
    """SQL rewriting a whole ``name="old"`` attribute value in ``expr``.

    :param str expr: SQL expression holding one language's arch, unescaped
    :param str old: name as it was written
    :param str new: name to write instead
    :return: SQL expression with the rename applied
    :rtype: str
    """
    return rf"""replace({expr}, 'name="{old}"', 'name="{new}"')"""


def _rewrite_xpath_predicate(expr, old, new):
    """SQL rewriting an ``@name='old'`` xpath predicate in ``expr``.

    An inheriting view targets the button by predicate rather than by attribute,
    so the two spellings are quoted differently and neither substitution finds
    the other.

    :param str expr: SQL expression holding one language's arch, unescaped
    :param str old: name as it was written
    :param str new: name to write instead
    :return: SQL expression with the rename applied
    :rtype: str
    """
    return rf"""replace({expr}, '@name=''{old}''', '@name=''{new}''')"""


def _rename_view_buttons(cr):
    """Repoint every stored arch that names a renamed button, before the XML loads.

    Rewriting goes through ``jsonb_each_text`` and not ``arch_db::text``, and the
    difference is the whole correctness of this script. ``arch_db`` is a jsonb map
    of language to arch, so its text rendering escapes every attribute quote --
    the stored bytes read ``name=\\"do_unreserve\\"``, and a pattern spelling
    ``name="do_unreserve"`` matches nothing at all while reporting success.
    Decomposing to values instead hands each language its arch unescaped, and
    ``jsonb_object_agg`` puts the map back with every language kept.

    Runs over active and inactive views alike: an inactive view is one
    reactivation away from being validated, and carries the same stale name.

    :param cr: database cursor
    :return: rewritten row count per old name, omitting the names that moved nothing
    :rtype: dict
    """
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
    """Archs still naming an old button by a route the two substitutions miss.

    A single-quoted attribute (``name='old'``) and an occurrence on a model the
    rename is not scoped to are both possible and neither is safe to rewrite
    blind -- the first because Odoo's serializer does not produce it, so a view
    spelling it that way was written by hand, and the second because a same-named
    button on an unrelated model belongs to somebody else.

    :param cr: database cursor
    :return: surviving view ids per old name
    :rtype: dict
    """
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
    """Rows still reaching an old method by a route the rewrite cannot take.

    1.23's two: whitespace around the dot, and getattr with a string literal.

    :param cr: database cursor
    :param str table: table holding stored Python
    :param str column: column holding stored Python
    :return: surviving row ids per old name
    :rtype: dict
    """
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
    """Carry the button renames into the two bindings the upgrade cannot reach.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
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
