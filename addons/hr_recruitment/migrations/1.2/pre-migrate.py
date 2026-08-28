r"""Pre-migration: ``hr.job.is_favorite`` is now ``is_user_favorite``.

The relation table behind ``favorite_user_ids`` keeps its hand-picked name:
``interviewer_ids`` is an implicit m2m to ``res.users`` and already occupies the
one the ORM would derive for the adopter, so this model overrides ``relation=``
rather than converging on it.

The field is ``store=False``, so nothing in this module's tables moves and no
column is renamed. What moves is every stored artifact naming it in a domain --
and a domain naming a field the registry no longer has raises on read, not on
upgrade, so an unrewritten filter fails later and somewhere else. Module-owned
view arch is reloaded from XML by the upgrade itself; these statements exist for
the artifacts users made.

Every statement is idempotent: the guard stops matching once a row is rewritten.
"""

OLD = "is_favorite"
NEW = "is_user_favorite"
MODEL = "hr.job"


def _rewrite(expr):
    """SQL rewriting the token whole-word in ``expr``.

    :param str expr: SQL expression (column or cast) to rewrite
    :return: SQL expression with the rename applied
    :rtype: str
    """
    return rf"regexp_replace({expr}, '\y{OLD}\y', '{NEW}', 'g')"


def _matches(expr):
    """SQL guard true when ``expr`` still names the old field.

    :param str expr: SQL expression (column or cast) to test
    :return: SQL boolean expression
    :rtype: str
    """
    return rf"{expr} ~ '\y{OLD}\y'"


def migrate(cr, version):
    """Repoint stored domains from the old field name to the new one.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    cr.execute(
        f"""
        UPDATE ir_ui_view
           SET arch_db = {_rewrite("arch_db::text")}::jsonb
         WHERE {_matches("arch_db::text")}
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
