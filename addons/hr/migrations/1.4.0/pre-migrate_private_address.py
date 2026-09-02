r"""Pre-migration: move the six private_* address columns onto a child partner.

The columns become non-stored `related` fields onto
``private_address_id``, so this has to run BEFORE the ORM drops them -- a
post-migration would find the data already gone.

It runs as SQL rather than through the ORM on purpose. The related fields do not
exist yet at pre-migration time, and reading the old columns through a model
whose declaration no longer has them is not available.

Idempotent: an employee that already has a private address is skipped, so a
re-run after a partial upgrade does not create a second one.
"""

import logging

_logger = logging.getLogger(__name__)

COLUMNS = ("street", "street2", "city", "zip", "state_id", "country_id")


def migrate(cr, version):
    if not version:
        return

    cr.execute("SELECT to_regclass('hr_employee')")
    if not cr.fetchone()[0]:
        return

    cr.execute(
        """SELECT column_name FROM information_schema.columns
            WHERE table_name = 'hr_employee' AND column_name LIKE 'private\\_%'"""
    )
    present = {row[0] for row in cr.fetchall()}
    missing = {f"private_{c}" for c in COLUMNS} - present
    if missing:
        _logger.info("Private address columns already moved (%s absent).", missing)
        return

    cr.execute(
        "ALTER TABLE hr_employee ADD COLUMN IF NOT EXISTS private_address_id integer"
    )

    # One private child per work contact, carrying the six values across.
    cr.execute(
        """
        WITH movable AS (
            SELECT e.id AS employee_id, e.work_contact_id,
                   e.private_street, e.private_street2, e.private_city,
                   e.private_zip, e.private_state_id, e.private_country_id
              FROM hr_employee e
             WHERE e.work_contact_id IS NOT NULL
               AND e.private_address_id IS NULL
               AND (e.private_street IS NOT NULL OR e.private_street2 IS NOT NULL
                 OR e.private_city IS NOT NULL OR e.private_zip IS NOT NULL
                 OR e.private_state_id IS NOT NULL OR e.private_country_id IS NOT NULL)
        ), created AS (
            INSERT INTO res_partner
                (parent_id, type, active, street, street2, city, zip, state_id,
                 country_id, company_id, create_uid, write_uid, create_date, write_date)
            SELECT m.work_contact_id, 'private', true, m.private_street,
                   m.private_street2, m.private_city, m.private_zip,
                   m.private_state_id, m.private_country_id, p.company_id,
                   1, 1, now(), now()
              FROM movable m JOIN res_partner p ON p.id = m.work_contact_id
            RETURNING id, parent_id
        )
        SELECT count(*) FROM created
        """
    )
    _logger.info("Created %s private address(es).", cr.fetchone()[0])

    cr.execute(
        """
        UPDATE hr_employee e
           SET private_address_id = p.id
          FROM res_partner p
         WHERE p.parent_id = e.work_contact_id
           AND p.type = 'private'
           AND e.private_address_id IS NULL
        """
    )
    linked = cr.rowcount

    cr.execute(
        """
        SELECT count(*) FROM hr_employee
         WHERE private_address_id IS NULL
           AND (private_street IS NOT NULL OR private_city IS NOT NULL
             OR private_zip IS NOT NULL OR private_country_id IS NOT NULL)
        """
    )
    stranded = cr.fetchone()[0]
    if stranded:
        _logger.warning(
            "%s employee(s) hold a private address but no work contact to hang "
            "it from; their columns are left in place rather than dropped.",
            stranded,
        )
    _logger.info("Linked %s employee(s) to a private address.", linked)
