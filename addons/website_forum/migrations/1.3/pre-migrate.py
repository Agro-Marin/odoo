RENAMES = (
    ("favourite_ids", "favorite_user_ids"),
    ("user_favourite", "is_user_favorite"),
    ("favourite_count", "favorite_count"),
)
MODEL = "forum.post"


def _rewrite(expr):
    for old, new in RENAMES:
        expr = rf"regexp_replace({expr}, '\y{old}\y', '{new}', 'g')"
    return expr


def _matches(expr):
    return " OR ".join(rf"{expr} ~ '\y{old}\y'" for old, _new in RENAMES)


def migrate(cr, version):
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
