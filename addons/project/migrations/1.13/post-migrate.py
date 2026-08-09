"""Post-migration for the 1.13 audit batch.

Four repairs, each undoing a state that existing databases can only be in
because of a defect that 1.13 fixes. All four are idempotent.

1. ``project.workflow.step.user_id`` is gone. The model split in 1.4 already
   routed personal stages to ``project.triage`` ("fields match
   project.task.type minus user_id"), but the field survived on the step model
   along with a create/write guard enforcing that a step was either a project
   step or somebody's personal stage. Nothing read it — no record rule, no
   view, no domain, and ``step_find`` searches ``project_ids`` alone — while
   the guard itself stamped an owner onto every column added from a project's
   Kanban board, because it inspected ``vals["project_ids"]`` and the board
   supplies the project through the field default. Drop the column.

2. Projects with no workflow step get one. Only ``name_create`` (the Many2one
   dropdown quick-create) ever seeded the default ``New`` step, so every
   project created from the form, an import or a script has an empty board.

3. Tasks with no step join their project's first one. Adding a column to a
   stepless project does not adopt the tasks already in it, so they would stay
   off the board forever.

4. ``deadline_met`` is cleared for cancelled tasks. The field now keys off
   DELIVERED_STATES rather than CLOSED_STATES: a cancelled task did not miss
   its deadline, it was abandoned, and counting it as a miss both punished
   teams for killing doomed work early and disagreed with
   ``project.deadline_compliance_pct``, which has always measured delivered
   work only.
"""

import logging

_logger = logging.getLogger(__name__)


def _drop_step_owner(cr) -> None:
    cr.execute("""
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'project_workflow_step'
           AND column_name = 'user_id'
    """)
    if not cr.fetchone():
        return
    cr.execute("ALTER TABLE project_workflow_step DROP COLUMN user_id")
    _logger.info("project_workflow_step.user_id dropped (vestigial since 1.4)")


def _seed_missing_steps(cr) -> None:
    cr.execute("""
        WITH stepless AS (
            SELECT p.id
              FROM project_project p
         LEFT JOIN project_workflow_step_project_rel rel ON rel.project_id = p.id
             WHERE rel.step_id IS NULL
        ), created AS (
            INSERT INTO project_workflow_step (name, sequence, active,
                                               rating_status, rating_status_period,
                                               create_date, write_date)
            SELECT '{"en_US": "New"}'::jsonb, 1, TRUE, 'stage', 'monthly',
                   NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC'
              FROM stepless
         RETURNING id
        ), numbered_steps AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn FROM created
        ), numbered_projects AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn FROM stepless
        )
        INSERT INTO project_workflow_step_project_rel (step_id, project_id)
        SELECT s.id, p.id
          FROM numbered_steps s
          JOIN numbered_projects p ON p.rn = s.rn
    """)
    if cr.rowcount:
        _logger.info("seeded a default workflow step for %d project(s)", cr.rowcount)


def _adopt_stepless_tasks(cr) -> None:
    cr.execute("""
        UPDATE project_task t
           SET step_id = first_step.step_id
          FROM (
                SELECT DISTINCT ON (rel.project_id)
                       rel.project_id, rel.step_id
                  FROM project_workflow_step_project_rel rel
                  JOIN project_workflow_step s ON s.id = rel.step_id
                 WHERE s.active
              ORDER BY rel.project_id, s.fold NULLS FIRST, s.sequence, s.id
               ) AS first_step
         WHERE t.project_id = first_step.project_id
           AND t.step_id IS NULL
    """)
    if cr.rowcount:
        _logger.info(
            "attached %d stepless task(s) to their project's first step", cr.rowcount
        )


def _clear_cancelled_deadline_met(cr) -> None:
    cr.execute("""
        UPDATE project_task
           SET deadline_met = NULL
         WHERE state = 'canceled'
           AND deadline_met IS NOT NULL
    """)
    if cr.rowcount:
        _logger.info("cleared deadline_met on %d cancelled task(s)", cr.rowcount)


def migrate(cr, version) -> None:
    if not version:
        return
    _drop_step_owner(cr)
    _seed_missing_steps(cr)
    _adopt_stepless_tasks(cr)
    _clear_cancelled_deadline_met(cr)
