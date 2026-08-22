r"""Pre-migration: ``repair.order.search_date_category`` is now ``date_category``.

The field is ``store=False``, so nothing in *this* module's tables moves and no
column is renamed. What does move is every stored artifact that names the field in
a domain — and a domain naming a field the registry no longer has raises on read,
not on upgrade, so an unrewritten favourite fails later and somewhere else.

Rewritten here, scoped to ``repair.order`` rather than swept globally: user-edited view
arch, saved filters, and window actions. Module-owned view arch is reloaded from
XML by the upgrade itself and needs nothing.

The old spelling carried its own mechanism in its name — ``search_`` said "this
field exists to be searched" — which forced the search hook to be spelled
``_search_search_date_category`` under ADR-0049. Naming the field for what it
holds makes the existing ``_search_date_category`` correct as it stands, and
joins the vocabulary ``stock/models/date_category_mixin.py`` already uses
(``date_category_to_domain``, ``calculate_date_category``).

Every statement is idempotent: the guard stops matching once a row is rewritten.
"""

OLD = "search_date_category"
NEW = "date_category"
MODEL = "repair.order"


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
