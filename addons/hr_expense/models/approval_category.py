from odoo import models


class ApprovalCategory(models.Model):
    _inherit = "approval.category"

    def _get_financial_verb(self) -> str:
        xmlid = self.env["hr.expense"]._get_approval_category_xmlid()
        if self == self.env.ref(xmlid, raise_if_not_found=False):
            return self.env._("reimbursing an expense")
        return super()._get_financial_verb()
