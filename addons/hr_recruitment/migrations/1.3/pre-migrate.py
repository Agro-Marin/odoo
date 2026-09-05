from odoo.db import schema

OLD = "type_id"
NEW = "degree_id"
MODEL = "hr.applicant"
TABLE = "hr_applicant"


def _rewrite(expr):
    return rf"regexp_replace({expr}, '\y{OLD}\y', '{NEW}', 'g')"


def _matches(expr):
    return rf"{expr} ~ '\y{OLD}\y'"


def migrate(cr, version):
    if not version:
        return

    if schema.column_exists(cr, TABLE, OLD) and not schema.column_exists(
        cr, TABLE, NEW
    ):
        cr.execute(f'ALTER TABLE "{TABLE}" RENAME COLUMN "{OLD}" TO "{NEW}"')

    cr.execute(
        """
        UPDATE ir_model_fields
           SET name = %s
         WHERE model = %s AND name = %s
        """,
        (NEW, MODEL, OLD),
    )
    cr.execute(
        f"""
        UPDATE ir_model_data
           SET name = 'field_hr_applicant__{NEW}'
         WHERE module = 'hr_recruitment' AND name = 'field_hr_applicant__{OLD}'
        """
    )
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
