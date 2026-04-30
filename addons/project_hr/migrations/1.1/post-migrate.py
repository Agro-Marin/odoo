"""Backfill resource.reservation rows for legacy project.task records (t20171).

When ``resource.scheduling.mixin`` was introduced (t21163), its CRUD
hooks created reservations on every create/write of project.task.
Pre-existing tasks (with planned dates and assigned employees but no
edits since the mixin landed) have no reservations, leaving
``allocated_hours = 0`` after the t20171 PMI refactor (where
``allocated_hours = sum(reservation_ids.allocated_hours)``).

This migration triggers ``_sync_reservations()`` on every active task
with the canonical scheduling triple (planned_date_begin + date_end +
at least one employee_id) that does not yet have a reservation.  It
processes in batches of 500 with intermediate commits so the upgrade
transaction stays bounded.

Idempotent: tasks that already have reservations are skipped by the
SQL filter; running this migration twice is a no-op on the second run.

Empirical scope at design time (marin190 production clone): 2250 tasks
need backfill, ~2348 reservations to create.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    cr.execute("""
        SELECT pt.id
        FROM project_task pt
        WHERE pt.active = TRUE
          AND pt.planned_date_begin IS NOT NULL
          AND pt.date_end IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM project_task_employee_rel rel
              WHERE rel.task_id = pt.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM resource_reservation rr
              WHERE rr.res_model = 'project.task'
                AND rr.res_id = pt.id
          )
    """)
    task_ids = [row[0] for row in cr.fetchall()]
    total = len(task_ids)
    if not total:
        _logger.info("project_hr 1.1: no tasks need reservation backfill.")
        return

    _logger.info(
        "project_hr 1.1: backfilling reservations for %d tasks "
        "(batches of %d).",
        total,
        BATCH_SIZE,
    )

    Task = env["project.task"].with_context(active_test=False)
    processed = 0
    for offset in range(0, total, BATCH_SIZE):
        batch_ids = task_ids[offset : offset + BATCH_SIZE]
        batch = Task.browse(batch_ids).exists()
        if batch:
            batch._sync_reservations()
        cr.commit()
        processed += len(batch)
        _logger.info(
            "project_hr 1.1: %d / %d tasks processed.",
            processed,
            total,
        )

    _logger.info(
        "project_hr 1.1: backfill complete (%d tasks).",
        processed,
    )
