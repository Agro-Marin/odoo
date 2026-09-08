from odoo.db.schema import column_exists

SOURCES = (
    (
        "event_registration",
        "phone",
        "landline",
        "event_registration_phone_number_rel",
        "registration_id",
    ),
)

SANITIZE = r"""
    regexp_replace(
        regexp_replace({col}, '[\s\\./\(\)\-]', '', 'g'),
        '^00', '+'
    )
"""


def migrate(cr, version):
    if not version:
        return
    for table, column, phone_type, rel, owner_column in SOURCES:
        if not column_exists(cr, table, column):
            continue
        sanitized = SANITIZE.format(col=f"src.{column}")
        cr.execute(
            f"""
            INSERT INTO phone_number
                (number, sanitized, type, active, "primary", sequence,
                 create_date, write_date, create_uid, write_uid)
            SELECT DISTINCT ON ({sanitized})
                   src.{column}, {sanitized}, %s, TRUE, FALSE, 10,
                   now(), now(), 1, 1
              FROM {table} src
             WHERE src.{column} IS NOT NULL AND btrim(src.{column}) <> ''
               AND {sanitized} <> ''
            ON CONFLICT (sanitized) DO NOTHING
            """,
            (phone_type,),
        )
        cr.execute(
            f"""
            INSERT INTO {rel} ({owner_column}, phone_number_id)
            SELECT src.id, pn.id
              FROM {table} src
              JOIN phone_number pn ON pn.sanitized = {sanitized}
             WHERE src.{column} IS NOT NULL AND btrim(src.{column}) <> ''
            ON CONFLICT DO NOTHING
            """
        )
        cr.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
