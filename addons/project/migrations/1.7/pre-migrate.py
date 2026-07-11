"""Pre-migration: PMI hours model on project.task (t20171).

Introduces the three-tier hours model:

- ``scheduled_hours``  — Duration in working time units (auto-computed
  from ``planned_date_begin`` / ``date_end`` against the company
  calendar).
- ``planned_resources`` — Integer, planning intent: how many parallel
  resources the PM expects to need.  Defaults to 1.
- ``planned_hours`` — Effort: ``scheduled_hours × planned_resources ×
  (allocated_percentage / 100)``, with manual override.
- ``allocated_hours`` — already present, computed by the scheduling
  mixin as ``sum(reservation_ids.allocated_hours)``.
- ``allocation_state`` — Selection signal of planning health (mirrors
  invoice_state on sale.order).

Migration steps:

1. Add ``scheduled_hours`` (numeric, blank — recomputed in post-migrate).
2. Add ``planned_resources`` (integer, default 1 for all existing tasks).
3. Add ``planned_hours`` (numeric, blank — recomputed in post-migrate).
4. Add ``allocation_state`` (varchar, blank — recomputed in post-migrate).
5. Drop legacy ``unallocated_hours`` column if present.

Legacy ``allocated_hours`` values are NOT copied into ``planned_hours``:
the post-migrate forces a fresh recompute of all three PMI fields from
the canonical inputs (dates, calendar, resources, allocated_percentage).
Tasks without dates land at ``planned_hours = 0`` and ``allocation_state
= unestimated``, which is the honest representation.

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

    # planned_hours: column-only.  Value is recomputed in post-migrate
    # from scheduled_hours x planned_resources x allocated_percentage.
    if not _column_exists(cr, "project_task", "planned_hours"):
        cr.execute("ALTER TABLE project_task ADD COLUMN planned_hours numeric")

    # scheduled_hours: column-only.  Value is recomputed in post-migrate.
    if not _column_exists(cr, "project_task", "scheduled_hours"):
        cr.execute("ALTER TABLE project_task ADD COLUMN scheduled_hours numeric")

    # planned_resources: planning intent, default 1 for legacy tasks.
    # Defensive cleanup against NULL / non-positive values before the
    # CHECK (planned_resources > 0) constraint loads with the model.
    if not _column_exists(cr, "project_task", "planned_resources"):
        cr.execute(
            "ALTER TABLE project_task ADD COLUMN planned_resources integer DEFAULT 1"
        )
    cr.execute(
        "UPDATE project_task SET planned_resources = 1 "
        "WHERE planned_resources IS NULL OR planned_resources <= 0"
    )
    # Ensure CHECK constraint is present even if _auto_init does not
    # re-trigger on a same-version reinstall.  Idempotent.
    cr.execute("""
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_task_planned_resources_positive'
    """)
    if not cr.fetchone():
        cr.execute("""
            ALTER TABLE project_task
            ADD CONSTRAINT project_task_planned_resources_positive
            CHECK (planned_resources > 0)
        """)

    # allocation_state: computed lazily on first read.
    if not _column_exists(cr, "project_task", "allocation_state"):
        cr.execute("ALTER TABLE project_task ADD COLUMN allocation_state varchar")

    # Drop the obsolete unallocated_hours column from an earlier draft of
    # the PMI model (replaced by allocation_state).
    if _column_exists(cr, "project_task", "unallocated_hours"):
        cr.execute("ALTER TABLE project_task DROP COLUMN unallocated_hours")
