def migrate(cr, version):
    if not version:
        return
    # The stored flag only depended on journal_id, so a line whose account or
    # whose journal's default account changed kept the value of its creation.
    cr.execute(
        """
        UPDATE account_move_line aml
           SET exclude_bank_lines = aml.account_id IS DISTINCT FROM j.default_account_id
          FROM account_journal j
         WHERE j.id = aml.journal_id
           AND aml.exclude_bank_lines IS DISTINCT FROM (
                   aml.account_id IS DISTINCT FROM j.default_account_id
               )
        """
    )
