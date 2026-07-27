"""Move delayed ``ir.job`` rows out of ``pending`` into the new ``scheduled``
state.

``pending`` now means "claimable this instant"; a job waiting on its ``eta``
lives in ``scheduled`` until ``IrJob._promote_due_jobs`` moves it over.  Rows
enqueued before that split are ``pending`` with a future ``eta``, and nothing
would ever run them: the claim query filters them out on ``eta``, while the
promotion sweep only looks at ``scheduled``.  They would sit in the queue
forever, counted as ready by every gauge.

Runs as a ``pre`` migration so the rows are correct before the new
``ir_job_due_idx`` and the widened ``ir_job_identity_uniq`` are built.
Idempotent: re-running matches nothing.
"""


def migrate(cr, version):
    cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'ir_job'")
    if not cr.rowcount:
        return
    cr.execute(
        """
        UPDATE ir_job
           SET state = 'scheduled'
         WHERE state = 'pending'
           AND eta IS NOT NULL
           AND eta > (now() AT TIME ZONE 'UTC')
        """
    )
