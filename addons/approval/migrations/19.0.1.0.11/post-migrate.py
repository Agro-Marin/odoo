import logging

_logger = logging.getLogger(__name__)

_COMPANY_SCOPED = (
    ("approval_request", True),
    ("approval_tier", True),
    ("approval_rule", True),
)


def migrate(cr, version):
    cr.execute("SELECT currency_id FROM res_company ORDER BY id LIMIT 1")
    row = cr.fetchone()
    if not row or not row[0]:
        _logger.warning("19.0.1.0.11: no company currency found; skipping backfill.")
        return
    main_currency_id = row[0]

    for table, _has_company in _COMPANY_SCOPED:
        cr.execute(
            f"""
            UPDATE {table} t
            SET currency_id = rc.currency_id
            FROM res_company rc
            WHERE t.company_id = rc.id
              AND rc.currency_id IS NOT NULL
              AND t.currency_id IS DISTINCT FROM rc.currency_id
            """,
        )
        scoped = cr.rowcount
        cr.execute(
            f"""
            UPDATE {table}
            SET currency_id = %s
            WHERE currency_id IS NULL
            """,
            (main_currency_id,),
        )
        globals_ = cr.rowcount
        if scoped or globals_:
            _logger.info(
                "19.0.1.0.11: backfilled currency_id on %s (%d scoped, %d global).",
                table,
                scoped,
                globals_,
            )
