from odoo import fields, models


class ApprovalCategory(models.Model):
    _inherit = "approval.category"

    target_model = fields.Selection(
        selection_add=[("approval.test.document", "Approval Test Document")],
        ondelete={"approval.test.document": "cascade"},
    )
