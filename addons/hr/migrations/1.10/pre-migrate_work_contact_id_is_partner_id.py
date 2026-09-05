import logging

from odoo.db import schema
from odoo.tools import SQL

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    if schema.column_exists(cr, "hr_employee", "work_contact_id") and not (
        schema.column_exists(cr, "hr_employee", "partner_id")
    ):
        cr.execute(
            SQL("ALTER TABLE hr_employee RENAME COLUMN work_contact_id TO partner_id")
        )
        _logger.info("hr_employee.work_contact_id renamed to partner_id")
    cr.execute(
        SQL(
            "UPDATE ir_model_fields SET name = 'partner_id'"
            " WHERE model IN ('hr.employee', 'hr.employee.public')"
            " AND name = 'work_contact_id'"
            " AND NOT EXISTS (SELECT 1 FROM ir_model_fields f2"
            " WHERE f2.model = ir_model_fields.model AND f2.name = 'partner_id')"
        )
    )
