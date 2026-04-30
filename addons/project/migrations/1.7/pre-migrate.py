"""Pre-migration: PMI hours model on project.task (t20171).

Introduces the three-tier hours model:

- ``scheduled_hours``  — Duration in working time units (auto-computed
  from ``planned_date_begin`` / ``date_end`` against the company
  calendar).
- ``planned_resources`` — Integer, planning intent: how many parallel
  resources the PM expects to need.  Defaults to 1.
- ``planned_hours`` — Effort: ``scheduled_hours × planned_resources``,
  with manual override.  Pre-existing values are preserved (they
  represent the legacy effort estimate).
- ``allocated_hours`` — already present, computed by the scheduling
  mixin as ``sum(reservation_ids.allocated_hours)``.
- ``allocation_state`` — Selection signal of planning health (mirrors
  invoice_state on sale.order).

Migration steps:

1. Add ``scheduled_hours`` (numeric, computed lazily on first read).
2. Add ``planned_resources`` (integer, default 1 for all existing tasks).
3. Add ``allocation_state`` (varchar, computed lazily).
4. Backfill ``planned_hours`` from the legacy ``allocated_hours`` so
   dashboards reading it as estimate keep their numbers — the value
   represents PMI Effort intent and remains correct even after the
   compute formula changes.
5. (Optional) The old ``unallocated_hours`` column from an earlier
   draft is dropped if present — superseded by ``allocation_state``.

Idempotent: safe to re-run on partially migrated databases.

See ``knowledge/agromarin-knowledge/reference/business/pmi-hours-model.md``.
"""


def _column_exists(cr, table, column):
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        [table, column],
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    if not _column_exists(cr, "project_task", "allocated_hours"):
        # Fresh install or model not yet present; nothing to seed.
        return

    # planned_hours: backfill from legacy allocated_hours (effort intent).
    if not _column_exists(cr, "project_task", "planned_hours"):
        cr.execute("ALTER TABLE project_task ADD COLUMN planned_hours numeric")
        cr.execute("UPDATE project_task SET planned_hours = allocated_hours")

    # scheduled_hours: computed lazily on first read; column added empty.
    if not _column_exists(cr, "project_task", "scheduled_hours"):
        cr.execute("ALTER TABLE project_task ADD COLUMN scheduled_hours numeric")

    # planned_resources: planning intent, default 1 for legacy tasks.
    if not _column_exists(cr, "project_task", "planned_resources"):
        cr.execute(
            "ALTER TABLE project_task "
            "ADD COLUMN planned_resources integer DEFAULT 1"
        )
        cr.execute(
            "UPDATE project_task SET planned_resources = 1 "
            "WHERE planned_resources IS NULL"
        )

    # allocation_state: computed lazily on first read.
    if not _column_exists(cr, "project_task", "allocation_state"):
        cr.execute(
            "ALTER TABLE project_task ADD COLUMN allocation_state varchar"
        )

    # Drop the obsolete unallocated_hours column from an earlier draft of
    # the PMI model (replaced by allocation_state).
    if _column_exists(cr, "project_task", "unallocated_hours"):
        cr.execute("ALTER TABLE project_task DROP COLUMN unallocated_hours")
