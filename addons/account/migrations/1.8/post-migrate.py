import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        ALTER TABLE account_reconcile_model_line
         DROP COLUMN IF EXISTS amount
        """
    )
    _logger.info("account.reconcile.model.line: dropped the orphan `amount` column")

    cr.execute(
        """
        UPDATE account_reconcile_model
           SET match_amount_min = COALESCE(match_amount_min, 0.0),
               match_amount_max = COALESCE(match_amount_max, 0.0)
         WHERE match_amount_min IS NULL
            OR match_amount_max IS NULL
        """
    )
    _logger.info(
        "account.reconcile.model: normalised %s row(s) whose amount bounds were NULL",
        cr.rowcount,
    )

    cr.execute(
        """
        UPDATE account_reconcile_model
           SET active = FALSE
         WHERE active IS TRUE
           AND match_label IS NOT NULL
           AND COALESCE(match_label_param, '') = ''
     RETURNING id, name ->> 'en_US'
        """
    )
    disabled = cr.fetchall()
    if disabled:
        _logger.warning(
            "account.reconcile.model: archived %s model(s) whose %s filter carried no "
            "text -- they matched nothing before this upgrade and would have matched "
            "everything after it: %s",
            len(disabled),
            "match_label",
            ", ".join(f"{name} (id {model_id})" for model_id, name in disabled),
        )
