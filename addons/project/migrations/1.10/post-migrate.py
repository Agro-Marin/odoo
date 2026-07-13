"""Post-migration for the benefit review-reminder marker (1.10).

``project.benefit`` gains ``review_reminder_date`` so the daily review cron
schedules at most one reminder per ``review_date`` — previously it re-created
the reminder every day once the accountable owner completed (deleted) it.

Backfill the marker for benefits that already have an open reminder activity,
so the first post-upgrade cron run treats them as "already reminded" and does
not raise a fresh duplicate nag. Runs post-migrate: the new column exists by now.

Idempotent: re-running only re-sets the marker to the same value.
"""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE project_benefit b
           SET review_reminder_date = b.review_date
          FROM mail_activity a
         WHERE a.res_model = 'project.benefit'
           AND a.res_id = b.id
           AND b.review_date IS NOT NULL
           AND b.review_reminder_date IS DISTINCT FROM b.review_date
        """
    )
