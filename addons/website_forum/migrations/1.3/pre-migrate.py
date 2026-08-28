r"""Pre-migration: ``forum.post`` favorites move onto ``mixin.user.favorite``.

``favourite_ids`` is now ``favorite_user_ids``, ``user_favourite`` is now
``is_user_favorite`` and ``favourite_count`` is now ``favorite_count`` -- the
last field-level spelling of the British form in the tree. The relation table
does not move: this model already left it implicit, and the name the mixin
derives is the same one, ``forum_post_res_users_rel``.

``favorite_count`` IS stored, and the schema pass renames its column on its own
only if told to; it is a ``fields.Count``, recomputed from
``favorite_user_ids``, so the new column is repopulated rather than carried.

The renamed boolean is ``store=False``, so no column of its own moves. What
moves is every stored artifact naming a renamed field -- and a domain naming a
field the registry no longer has raises when the domain is READ, not when the
module is upgraded, so an unrewritten filter fails later and elsewhere.
Module-owned view arch is reloaded from XML by the upgrade itself; these
statements exist for the artifacts users made.

Every statement is idempotent: the guard stops matching once a row is rewritten.
"""

RENAMES = (
    ("favourite_ids", "favorite_user_ids"),
    ("user_favourite", "is_user_favorite"),
    ("favourite_count", "favorite_count"),
)
MODEL = "forum.post"


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
