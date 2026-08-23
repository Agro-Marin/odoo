import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # allowed_account_ids became enforced in this version. Existing posted items are
    # never re-validated, so an upgrade cannot fail here -- but the next write to one
    # of these journals will, and the operator is better told now than then.
    cr.execute(
        """
        SELECT j.id, j.code, count(DISTINCT aml.account_id)
          FROM account_journal j
          JOIN account_journal_allowed_account_rel allowed ON allowed.journal_id = j.id
          JOIN account_move_line aml ON aml.journal_id = j.id
         WHERE aml.display_type IS DISTINCT FROM 'line_section'
           AND aml.display_type IS DISTINCT FROM 'line_subsection'
           AND aml.display_type IS DISTINCT FROM 'line_note'
           AND aml.account_id IS NOT NULL
           AND NOT EXISTS (
                   SELECT 1 FROM account_journal_allowed_account_rel r
                    WHERE r.journal_id = j.id AND r.account_id = aml.account_id
               )
           AND aml.account_id IS DISTINCT FROM j.default_account_id
           AND aml.account_id IS DISTINCT FROM j.suspense_account_id
           AND aml.account_id IS DISTINCT FROM j.non_deductible_account_id
           AND aml.account_id IS DISTINCT FROM j.profit_account_id
           AND aml.account_id IS DISTINCT FROM j.loss_account_id
      GROUP BY j.id, j.code
      ORDER BY 3 DESC
        """
    )
    offenders = cr.fetchall()
    if not offenders:
        _logger.info("allowed_account_ids: no journal has items outside its list")
        return

    _logger.warning(
        "allowed_account_ids is now enforced and %s journal(s) hold items on "
        "accounts their list excludes; widen the list or those journals will "
        "refuse the next write: %s",
        len(offenders),
        ", ".join(f"{code} ({count} account(s))" for _id, code, count in offenders),
    )
