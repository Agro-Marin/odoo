r"""Pre-migration: ``stock.picking.search_date_category`` is now ``date_category``.

The field moved onto ``mixin.date.category``, which declares it once for every
consumer instead of each model declaring its own. Naming it for what it holds
makes the existing ``_search_date_category`` its correctly-named search hook
(ADR-0049) -- the same rename ``repair`` 1.2 and ``mrp`` 2.4 carry.

Carried at 1.10 rather than 1.8 because both merge parents had already shipped
a 1.8 and a 1.9 for other work.
"""

OLD = "search_date_category"
NEW = "date_category"
MODEL = "stock.picking"


def _rewrite(expr):
    return rf"regexp_replace({expr}, '\y{OLD}\y', '{NEW}', 'g')"


def _matches(expr):
    return rf"{expr} ~ '\y{OLD}\y'"


def migrate(cr, version):
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
