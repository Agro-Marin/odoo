r"""Pre-migration: ``crm.team`` favorites move onto ``mixin.user.favorite``.

``is_favorite`` is now ``is_user_favorite`` and the relation table behind
``favorite_user_ids`` is the one the ORM derives for the adopter rather than a
hand-picked name.

The mixin declares ``favorite_user_ids`` without a ``relation=``, so
``Many2many.setup_nonrelated`` names the table from the *adopter's* table:
``crm_team_res_users_rel``, with columns ``crm_team_id`` and
``res_users_id``. Renaming here rather than letting the schema pass create the
new table is what carries the rows: an unrenamed table is simply orphaned, and
every existing favorite silently disappears.

``is_favorite`` is ``store=False``, so no column of its own moves. What moves is
every stored artifact naming it -- and a domain naming a field the registry no
longer has raises when the domain is READ, not when the module is upgraded, so an
unrewritten filter fails later and elsewhere. Module-owned view arch is reloaded
from XML by the upgrade itself; these statements exist for the artifacts users
made.

Every statement is idempotent: the guard stops matching once a row is rewritten.
"""

OLD = "is_favorite"
NEW = "is_user_favorite"
MODEL = "crm.team"

OLD_RELATION = "team_favorite_user_rel"
NEW_RELATION = "crm_team_res_users_rel"
COLUMNS = (("team_id", "crm_team_id"), ("user_id", "res_users_id"))


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


def _rename_relation(cr):
    """Carry the favorite rows onto the table name the mixin derives.

    :param cr: database cursor
    """
    cr.execute("SELECT to_regclass(%s)", (OLD_RELATION,))
    if not cr.fetchone()[0]:
        return
    cr.execute(f'ALTER TABLE "{OLD_RELATION}" RENAME TO "{NEW_RELATION}"')
    for old_column, new_column in COLUMNS:
        cr.execute(
            f'ALTER TABLE "{NEW_RELATION}" RENAME COLUMN "{old_column}"'
            f' TO "{new_column}"'
        )


def migrate(cr, version):
    """Rename the relation table and repoint stored domains at the new field.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    _rename_relation(cr)

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
