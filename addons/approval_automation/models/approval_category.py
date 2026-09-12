from odoo import fields, models

from odoo.addons.approval.models.approval_category import CATEGORY_SELECTION


class ApprovalCategory(models.Model):
    _inherit = "approval.category"

    has_automation = fields.Selection(
        CATEGORY_SELECTION,
        required=True,
        default="no",
        tracking=True,
        help="Automation flows that should be specified on the request.",
    )
    automation_id = fields.Many2one(
        comodel_name="automation.rule",
        domain="[('trigger', '=', 'on_hand')]",
    )
