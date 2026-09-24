from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    property_payment_term_id = fields.Many2one(
        comodel_name="account.payment.term",
        string="Customer Payment Terms",
        company_dependent=True,
        ondelete="restrict",
        check_company=True,
    )
    property_supplier_payment_term_id = fields.Many2one(
        comodel_name="account.payment.term",
        string="Vendor Payment Terms",
        company_dependent=True,
        check_company=True,
    )

    @api.model
    def _commercial_fields(self):
        return super()._commercial_fields() + [
            "property_payment_term_id",
            "property_supplier_payment_term_id",
        ]
