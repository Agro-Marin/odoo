import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute(
        """
        SELECT DISTINCT p.id
          FROM res_partner p
          JOIN res_partner_identifier i ON i.partner_id = p.id
         WHERE p.active
           AND NOT p.is_company
           AND p.parent_id IS NULL
           AND NOT EXISTS (SELECT 1 FROM res_users u WHERE u.partner_id = p.id)
           AND NOT EXISTS (SELECT 1 FROM hr_employee e WHERE e.partner_id = p.id)
           AND NOT EXISTS (
               SELECT 1 FROM res_partner c
                WHERE c.parent_id = p.id AND c.type <> 'private')
        """
    )
    orphans = env["res.partner"].browse([row[0] for row in cr.fetchall()])
    Employee = env["hr.employee"].with_context(active_test=False)
    rejoined = unmatched = 0
    for orphan in orphans:
        employees = Employee.search([("name", "=", orphan.name)])
        if len(employees) != 1:
            unmatched += 1
            _logger.warning(
                "orphan party %s (%s) holds identifiers and matches %s employees; left as is",
                orphan.id,
                orphan.name,
                len(employees),
            )
            continue
        employee = employees
        employee._move_identifiers_to_party({employee: orphan})
        employee._reparent_private_address()
        for home in orphan.child_ids.filtered(lambda c: c.type == "private"):
            home.parent_id = employee.partner_id
        employee._retire_former_party({employee: orphan})
        rejoined += 1
    _logger.info(
        "orphan parties: %s rejoined their employee, %s left for a human",
        rejoined,
        unmatched,
    )
