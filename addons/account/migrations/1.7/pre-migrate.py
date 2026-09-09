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
