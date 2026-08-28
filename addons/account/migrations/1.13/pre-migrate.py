# `status_in_payment` folds a move's lifecycle, whether it has been sent, and its
# settlement into the one status a list view shows. The name said none of that,
# and read as a state *inside* a payment -- which is the model next door.
#
# The field is computed and not stored, so there is no column: what needs moving
# is the places a database records the name. Views, filters and actions that ship
# in data files are reloaded by this upgrade; these statements are for the ones a
# user built by hand, which nothing reloads.
MODEL = "account.move"

OLD = "status_in_payment"
NEW = "display_state"


def _rewrite(expr):
    return rf"regexp_replace({expr}, '\y{OLD}\y', '{NEW}', 'g')"


def _matches(expr):
    return rf"{expr} ~ '\y{OLD}\y'"


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        "UPDATE ir_model_fields SET name = %s WHERE model = %s AND name = %s",
        (NEW, MODEL, OLD),
    )
    cr.execute(
        "UPDATE ir_model_data SET name = %s WHERE model = 'ir.model.fields' AND name = %s",
        (f"field_account_move__{NEW}", f"field_account_move__{OLD}"),
    )

    cr.execute(
        f"""
        UPDATE ir_ui_view
           SET arch_db = {_rewrite("arch_db::text")}::jsonb
         WHERE {_matches("arch_db::text")}
        """
    )
    cr.execute(
        f"""
        UPDATE ir_filters
           SET domain = {_rewrite("domain")},
               context = {_rewrite("context")},
               sort = {_rewrite("sort")}
         WHERE model_id = %s
           AND ({_matches("domain")} OR {_matches("context")} OR {_matches("sort")})
        """,
        (MODEL,),
    )
    cr.execute(
        f"""
        UPDATE ir_act_window
           SET domain = {_rewrite("domain")},
               context = {_rewrite("context")}
         WHERE res_model = %s
           AND ({_matches("domain")} OR {_matches("context")})
        """,
        (MODEL,),
    )
    cr.execute(
        f"""
        UPDATE ir_act_server a
           SET code = {_rewrite("a.code")}
          FROM ir_model m
         WHERE m.id = a.model_id AND m.model = %s AND {_matches("a.code")}
        """,
        (MODEL,),
    )
    cr.execute(
        """
        UPDATE ir_exports_line l
           SET name = %s
          FROM ir_exports e
         WHERE l.export_id = e.id AND e.resource = %s AND l.name = %s
        """,
        (NEW, MODEL, OLD),
    )
