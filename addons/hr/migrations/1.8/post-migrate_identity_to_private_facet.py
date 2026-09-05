import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

COLUMNS = {
    "sex": "gender",
    "birthday": "birthdate",
    "country_id": "nationality_id",
    "private_email": "email",
    "private_phone": "phone",
}


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        "SELECT id, sex, birthday, country_id, private_email, private_phone"
        " FROM hr_employee"
        " WHERE sex IS NOT NULL OR birthday IS NOT NULL OR country_id IS NOT NULL"
        " OR private_email IS NOT NULL OR private_phone IS NOT NULL"
    )
    rows = cr.fetchall()
    if not rows:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    employees = (
        env["hr.employee"]
        .with_context(active_test=False)
        .browse([row[0] for row in rows])
    )
    employees._compute_private_address_id()
    homes = {employee.id: employee.private_address_id for employee in employees}
    moved = skipped = 0
    for employee_id, *values in rows:
        home = homes[employee_id]
        if not home:
            skipped += 1
            continue
        home.write(
            {
                target: value
                for (column, target), value in zip(COLUMNS.items(), values, strict=True)
                if value is not None
            }
        )
        moved += 1
    _logger.info(
        "identity columns moved onto the private facet for %s employees, "
        "%s employees without a work contact kept theirs in the old columns",
        moved,
        skipped,
    )
