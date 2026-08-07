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
