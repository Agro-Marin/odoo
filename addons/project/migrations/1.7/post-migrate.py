import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE project_task pt
           SET company_id = p.company_id
          FROM project_project p
         WHERE pt.project_id = p.id
           AND pt.company_id IS NULL
           AND p.company_id IS NOT NULL
        """
    )
    from_project = cr.rowcount

    cr.execute(
        """
        UPDATE project_task pt
           SET company_id = u.company_id
          FROM res_users u
         WHERE pt.create_uid = u.id
           AND pt.company_id IS NULL
           AND u.company_id IS NOT NULL
        """
    )
    from_creator = cr.rowcount

    cr.execute(
        """
        UPDATE project_task pt
           SET company_id = u.company_id
          FROM (
              SELECT DISTINCT ON (rel.task_id)
                     rel.task_id, rel.user_id
                FROM project_task_user_rel rel
            ORDER BY rel.task_id, rel.user_id
          ) first_assignee
          JOIN res_users u ON u.id = first_assignee.user_id
         WHERE pt.id = first_assignee.task_id
           AND pt.company_id IS NULL
           AND u.company_id IS NOT NULL
        """
    )
    from_assignee = cr.rowcount

    if from_project + from_creator + from_assignee:
        _logger.info(
            "project 1.7: backfilled company_id on %d tasks "
            "(project=%d, creator=%d, assignee=%d).",
            from_project + from_creator + from_assignee,
            from_project,
            from_creator,
            from_assignee,
        )

    env = api.Environment(cr, SUPERUSER_ID, {})
    Task = env["project.task"].with_context(
        active_test=False,
        tracking_disable=True,
        mail_notrack=True,
        mail_create_nosubscribe=True,
    )
    tasks = Task.search([])
    if not tasks:
        _logger.info("project 1.7: no tasks to recompute.")
        return

    _logger.info(
        "project 1.7: recomputing PMI fields on %d tasks "
        "(scheduled_hours -> planned_hours -> allocation_state).",
        len(tasks),
    )
    tasks._compute_scheduled_hours()
    tasks._compute_planned_hours()
    tasks._compute_allocation_state()
    tasks.flush_recordset(["scheduled_hours", "planned_hours", "allocation_state"])
    _logger.info("project 1.7: PMI recompute complete.")
