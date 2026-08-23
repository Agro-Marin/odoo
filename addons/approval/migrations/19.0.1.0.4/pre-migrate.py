def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        UPDATE approval_request
           SET state = 'refused'
         WHERE state IN ('cancel', 'revision')
        """,
    )
    cr.execute(
        """
        UPDATE approval_approver
           SET state = 'refused'
         WHERE state IN ('cancel', 'revision')
        """,
    )

    cr.execute(
        """
        ALTER TABLE approval_request
          DROP COLUMN IF EXISTS revision_count
        """,
    )

    cr.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'approval_approver'
                   AND column_name = 'approval_note'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'approval_approver'
                   AND column_name = 'note'
            ) THEN
                ALTER TABLE approval_approver
                  RENAME COLUMN approval_note TO note;
            END IF;
        END $$;
        """,
    )
