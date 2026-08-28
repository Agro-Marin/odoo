r"""Pre-migration: ``spreadsheet.dashboard`` favorites move onto ``mixin.user.favorite``.

``is_favorite`` is now ``is_user_favorite``. The relation table behind
``favorite_user_ids`` does not move: this model already left it implicit, and the
name the mixin derives is the same one.

The renamed boolean is ``store=False``, so no column of its own moves. What
moves is every stored artifact naming a renamed field -- and a domain naming a
field the registry no longer has raises when the domain is READ, not when the
module is upgraded, so an unrewritten filter fails later and elsewhere.
Module-owned view arch is reloaded from XML by the upgrade itself; these
statements exist for the artifacts users made.

Every statement is idempotent: the guard stops matching once a row is rewritten.
"""

RENAMES = (("is_favorite", "is_user_favorite"),)
MODEL = "spreadsheet.dashboard"


def _rewrite(expr):
    """SQL rewriting every renamed token whole-word in ``expr``.

    :param str expr: SQL expression (column or cast) to rewrite
    :return: SQL expression with the renames applied
    :rtype: str
    """
    for old, new in RENAMES:
        expr = rf"regexp_replace({expr}, '\y{old}\y', '{new}', 'g')"
    return expr


def _matches(expr):
    """SQL guard true when ``expr`` still names one of the old fields.

    :param str expr: SQL expression (column or cast) to test
    :return: SQL boolean expression
    :rtype: str
    """
    return " OR ".join(rf"{expr} ~ '\y{old}\y'" for old, _new in RENAMES)


def migrate(cr, version):
    """Repoint stored domains from the old field names to the new ones.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    cr.execute(
        f"""
        UPDATE ir_ui_view
           SET arch_db = {_rewrite("arch_db::text")}::jsonb
         WHERE ({_matches("arch_db::text")})
           AND model = %s
        """,
        (MODEL,),
    )
    cr.execute(
        f"""
        UPDATE ir_filters
           SET domain = {_rewrite("domain")},
               context = {_rewrite("context")},
               sort = {_rewrite("sort")}
         WHERE ({_matches("domain")}
                OR {_matches("context")}
                OR {_matches("sort")})
           AND model_id = %s
        """,
        (MODEL,),
    )
    cr.execute(
        f"""
        UPDATE ir_act_window
           SET domain = {_rewrite("domain")},
               context = {_rewrite("context")}
         WHERE ({_matches("domain")} OR {_matches("context")})
           AND res_model = %s
        """,
        (MODEL,),
    )
