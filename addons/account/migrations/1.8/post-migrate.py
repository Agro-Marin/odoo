import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # account.reconcile.model.line.amount became a non-stored compute: nothing searched,
    # ordered or grouped on it, and a stored copy could be written to directly, leaving
    # the effective amount disagreeing with the amount_string the form shows. Odoo leaves
    # the orphan column behind, so drop it here rather than keep a shadow of the value.
    cr.execute(
        """
        ALTER TABLE account_reconcile_model_line
         DROP COLUMN IF EXISTS amount
        """
    )
    _logger.info("account.reconcile.model.line: dropped the orphan `amount` column")

    # match_amount_min / match_amount_max are read in SQL by the matching engine, where a
    # never-written column is NULL and every comparison against it is NULL -- so a model
    # whose amount filter was set after creation matched nothing at all, silently, while
    # the ORM and the form both reported 0.0. The engine now COALESCEs, and these rows are
    # normalised so the column agrees with what has always been displayed.
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

    # A label filter with no text used to be inert in both directions, because
    # ILIKE '%' || NULL || '%' is NULL and so is its negation. The matcher now reads
    # `not_contains` the way it is written, which would turn such a model from matching
    # nothing into matching everything -- and an automated one would then reconcile the
    # whole backlog on the first write. They are archived instead: that preserves what
    # they actually did, and a constraint now refuses the shape on the next edit.
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
