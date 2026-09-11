"""``hr.expense.approval_state`` becomes ``review_state``.

The expense keeps its own review (submitted / approved / refused) while
``mixin.approval`` brings ``approval_state`` as the mirror of the approval
request's state, so the two cannot share a name. The column is renamed in place
rather than left for the ORM, which would add the new column and orphan the old
one with its data. ``ir_model_fields`` is renamed alongside, and saved views,
filters, actions and export lines on ``hr.expense`` are rewritten: once the
expense adopts ``mixin.approval``, a stored reference to the old name would
silently read the request's state instead of failing.
"""

from odoo.db import schema

OLD = "approval_state"
NEW = "review_state"
# (model, table): the transient split wizard carries the field too.
MODELS = (("hr.expense", "hr_expense"), ("hr.expense.split", "hr_expense_split"))


def _rename_field_row(cr, model):
    cr.execute(
        """
        UPDATE ir_model_fields
           SET name = %s
         WHERE model = %s
           AND name = %s
           AND NOT EXISTS (
                 SELECT 1 FROM ir_model_fields WHERE model = %s AND name = %s
           )
        """,
        (NEW, model, OLD, model, NEW),
    )


def _rewrite_stored_references(cr, model):
    def rewrite(expr):
        return rf"regexp_replace({expr}, '\y{OLD}\y', '{NEW}', 'g')"

    def matches(expr):
        return rf"{expr} ~ '\y{OLD}\y'"

    cr.execute(
        f"""
        UPDATE ir_ui_view
           SET arch_db = {rewrite("arch_db::text")}::jsonb
         WHERE {matches("arch_db::text")}
           AND model = %s
        """,
        (model,),
    )
    cr.execute(
        f"""
        UPDATE ir_filters
           SET domain = {rewrite("domain")},
               context = {rewrite("context")},
               sort = {rewrite("sort")}
         WHERE ({matches("domain")} OR {matches("context")} OR {matches("sort")})
           AND model_id = %s
        """,
        (model,),
    )
    cr.execute(
        f"""
        UPDATE ir_act_window
           SET domain = {rewrite("domain")},
               context = {rewrite("context")}
         WHERE ({matches("domain")} OR {matches("context")})
           AND res_model = %s
        """,
        (model,),
    )
    cr.execute(
        f"""
        UPDATE ir_exports_line
           SET name = {rewrite("name")}
         WHERE {matches("name")}
           AND export_id IN (SELECT id FROM ir_exports WHERE resource = %s)
        """,
        (model,),
    )


def migrate(cr, version):
    if not version:
        return
    for model, table in MODELS:
        if schema.column_exists(cr, table, OLD) and not schema.column_exists(
            cr, table, NEW
        ):
            cr.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{OLD}" TO "{NEW}"')
        _rename_field_row(cr, model)
    _rewrite_stored_references(cr, "hr.expense")
