"""Field renames onto the family's canonical date_/is_/amount_ spellings.

Stored columns are renamed in place rather than left for the ORM, which would
add the new column and orphan the old one with its data. ``ir_model_fields`` is
renamed alongside so ``mail_tracking_value`` rows keep pointing at the same
field row -- ``project.milestone.deadline`` and ``project.gate.review_date`` are
both tracked, and dropping the row would take their history with it.
"""

# (model, old, new, rewrite_arch)
#
# rewrite_arch is False for ``met``: the name is a bare English word that also
# appears in labels and help text on the very views that carry the field, and a
# word-bounded rewrite cannot tell the two apart.
RENAMES = (
    ("project.task", "planned_date_begin", "date_start", True),
    ("project.task", "earliest_start", "cpm_date_earliest_start", True),
    ("project.task", "latest_start", "cpm_date_latest_start", True),
    ("project.milestone", "deadline", "date_deadline", True),
    ("project.milestone", "reached_date", "date_reached", True),
    ("project.baseline.line", "planned_start", "date_planned_start", True),
    ("project.baseline.line", "planned_end", "date_planned_end", True),
    ("project.benefit", "review_date", "date_review", True),
    ("project.benefit", "review_reminder_date", "date_review_reminder", True),
    ("project.gate", "review_date", "date_review", True),
    ("project.gate.criterion", "met", "is_met", False),
    ("project.retrospective.action", "due_date", "date_due", True),
    ("project.project", "premortem_date", "date_premortem", True),
    ("project.workflow.step", "rating_request_deadline", "date_rating_request", True),
)

TABLES = {
    "project.task": "project_task",
    "project.milestone": "project_milestone",
    "project.baseline.line": "project_baseline_line",
    "project.benefit": "project_benefit",
    "project.gate": "project_gate",
    "project.gate.criterion": "project_gate_criterion",
    "project.retrospective.action": "project_retrospective_action",
    "project.project": "project_project",
    "project.workflow.step": "project_workflow_step",
}


def _column_exists(cr, table, column):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = %s
           AND column_name = %s
        """,
        (table, column),
    )
    return bool(cr.fetchone())


def _rename_column(cr, table, old, new):
    if _column_exists(cr, table, old) and not _column_exists(cr, table, new):
        cr.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"')


def _rename_field_row(cr, model, old, new):
    cr.execute(
        """
        UPDATE ir_model_fields
           SET name = %s
         WHERE model = %s
           AND name = %s
           AND NOT EXISTS (
                 SELECT 1 FROM ir_model_fields
                  WHERE model = %s AND name = %s
           )
        """,
        (new, model, old, model, new),
    )


def _rewrite_stored_references(cr, model, old, new):
    rewrite = lambda expr: rf"regexp_replace({expr}, '\y{old}\y', '{new}', 'g')"
    matches = lambda expr: rf"{expr} ~ '\y{old}\y'"

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
         WHERE ({matches("domain")}
                OR {matches("context")}
                OR {matches("sort")})
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
           AND export_id IN (
                 SELECT id FROM ir_exports WHERE resource = %s
           )
        """,
        (model,),
    )


def migrate(cr, version):
    if not version:
        return

    for model, old, new, rewrite_arch in RENAMES:
        _rename_column(cr, TABLES[model], old, new)
        _rename_field_row(cr, model, old, new)
        if rewrite_arch:
            _rewrite_stored_references(cr, model, old, new)
