from odoo.db import schema

TABLE = "account_payment_term_line"
COLUMN = "days_next_month"
DEFAULT = 10


def migrate(cr, version):
    if not version:
        return
    if not schema.table_exists(cr, TABLE):
        return

    cr.execute(
        """
        SELECT data_type FROM information_schema.columns
         WHERE table_name = %s AND column_name = %s
        """,
        (TABLE, COLUMN),
    )
    row = cr.fetchone()
    if not row or row[0] == "integer":
        return

    # the column held a 2-character string; anything a human could type that is
    # not an ASCII number was never a valid day of the month, so it falls back
    # to the field default rather than blocking the upgrade
    cr.execute(
        f"""
        ALTER TABLE "{TABLE}"
        ALTER COLUMN "{COLUMN}" TYPE integer
        USING COALESCE(
            NULLIF(regexp_replace("{COLUMN}", '[^0-9]', '', 'g'), '')::integer,
            {DEFAULT}
        )
        """
    )
    cr.execute(
        f"""
        UPDATE "{TABLE}" SET "{COLUMN}" = {DEFAULT}
         WHERE "{COLUMN}" IS NULL OR "{COLUMN}" < 0 OR "{COLUMN}" > 31
        """
    )
