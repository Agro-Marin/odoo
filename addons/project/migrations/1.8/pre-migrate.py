"""Pre-migration for the PM-layer DB constraints added in 1.8.

Two new partial unique indexes are introduced with this version:

- ``project_baseline``: at most one ``is_current`` baseline per project.
- ``project_sprint``: at most one ``state = 'active'`` sprint per project.

Both invariants were previously enforced only in Python (``action_set_current``
/ ``action_start``), so direct create/write or imports could have produced
violating rows. ``_auto_init`` creates the indexes *after* this script runs, so
we must collapse any existing duplicates first or the index creation — and thus
the whole module upgrade — would fail.

Resolution policy (least surprising, deterministic):
- Baselines: keep the most recently created current baseline per project
  (``date_created DESC, id DESC``); unset ``is_current`` on the rest.
- Sprints: keep the most recently started active sprint per project
  (``date_start DESC, id DESC``); move the rest to ``state = 'review'`` (their
  natural next state), never to ``closed`` (which would release their tasks).

Idempotent: safe to re-run; if no duplicates exist it is a no-op.
"""


def _table_exists(cr, table):
    cr.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = %s",
        [table],
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    if _table_exists(cr, "project_baseline"):
        # Keep one current baseline per project (latest), unset the others.
        cr.execute(
            """
            UPDATE project_baseline
               SET is_current = FALSE
             WHERE is_current IS TRUE
               AND id NOT IN (
                   SELECT DISTINCT ON (project_id) id
                     FROM project_baseline
                    WHERE is_current IS TRUE
                    ORDER BY project_id, date_created DESC, id DESC
               )
            """
        )

    if _table_exists(cr, "project_sprint"):
        # Keep one active sprint per project (latest start), demote the rest to
        # 'review' so no project retains two concurrently active sprints.
        cr.execute(
            """
            UPDATE project_sprint
               SET state = 'review'
             WHERE state = 'active'
               AND id NOT IN (
                   SELECT DISTINCT ON (project_id) id
                     FROM project_sprint
                    WHERE state = 'active'
                    ORDER BY project_id, date_start DESC, id DESC
               )
            """
        )
