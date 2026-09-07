"""Pre-migration: the employee's work channels become its party's.

`base` 1.36 turns a phone number into a record a contact can share and drops
`res_partner.phone` and `res_partner.mobile`, and `base` always loads before
`hr`. So by the time this runs there are no partner columns left to copy into:
the numbers go to `phone.number` rows linked through
`res_partner_phone_number_rel`, exactly as `base` put the party's own numbers
there. The work email is untouched by that refactor and is still a column.

A party can hold several numbers now, so an employee's number is added to the
party's set rather than being weighed against a single existing value. Nothing
is discarded for conflicting with what the party already had.
"""

import logging

from odoo.db.schema import column_exists

_logger = logging.getLogger(__name__)

SANITIZE = r"""
    regexp_replace(
        regexp_replace({col}, '[\s\\./\(\)\-]', '', 'g'),
        '^00', '+'
    )
"""

# the employee's column -> the kind of number it is, and the party that owns it
PHONES = (
    ("work_phone", "landline", "partner_id"),
    ("mobile_phone", "mobile", "partner_id"),
    ("private_phone", "mobile", "private_address_id"),
)


def migrate(cr, version):
    if not version:
        return
    if column_exists(cr, "hr_employee", "work_email"):
        cr.execute(
            """
            UPDATE res_partner p
               SET email = e.work_email
              FROM hr_employee e
             WHERE e.partner_id = p.id
               AND e.work_email IS NOT NULL AND btrim(e.work_email) <> ''
               AND (p.email IS NULL OR p.email = '')
            """
        )
        _logger.info(
            "work channels: %s parties took the employee's work email", cr.rowcount
        )

    for column, phone_type, owner in PHONES:
        if not column_exists(cr, "hr_employee", column):
            continue
        sanitized = SANITIZE.format(col=f"e.{column}")
        cr.execute(
            f"""
            INSERT INTO phone_number
                (number, sanitized, type, active, "primary", sequence,
                 create_date, write_date, create_uid, write_uid)
            SELECT DISTINCT ON ({sanitized})
                   e.{column}, {sanitized}, %s, TRUE, FALSE, 10,
                   now(), now(), 1, 1
              FROM hr_employee e
             WHERE e.{owner} IS NOT NULL
               AND e.{column} IS NOT NULL AND btrim(e.{column}) <> ''
               AND {sanitized} <> ''
            ON CONFLICT (sanitized) DO NOTHING
            """,
            (phone_type,),
        )
        cr.execute(
            f"""
            INSERT INTO res_partner_phone_number_rel (partner_id, phone_number_id)
            SELECT e.{owner}, pn.id
              FROM hr_employee e
              JOIN phone_number pn ON pn.sanitized = {sanitized}
             WHERE e.{owner} IS NOT NULL
               AND e.{column} IS NOT NULL AND btrim(e.{column}) <> ''
            ON CONFLICT DO NOTHING
            """
        )
        _logger.info(
            "work channels: %s parties took the employee's %s", cr.rowcount, column
        )
        cr.execute(
            f"""
            SELECT count(*) FROM hr_employee e
             WHERE e.{owner} IS NULL
               AND e.{column} IS NOT NULL AND btrim(e.{column}) <> ''
            """
        )
        stranded = cr.fetchone()[0]
        if stranded:
            _logger.warning(
                "work channels: %s employees carry a %s but no %s to hang it on, "
                "so those numbers go with the column",
                stranded,
                column,
                owner,
            )
