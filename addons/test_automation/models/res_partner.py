from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # This module's own flag, not hr's `employee`. The tests need a WRITABLE
    # boolean on a second model to prove an automation fires when a compute
    # recomputes across a relation; hr's `employee` is a non-stored compute
    # derived from employments (c7a70fa3ede) and cannot be written, and hr is
    # not a dependency any base-automation test should carry.
    test_automation_employee = fields.Boolean()
