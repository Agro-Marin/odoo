from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    property_account_position_id = fields.Many2one(
        comodel_name="account.fiscal.position",
        string="Fiscal Position",
        company_dependent=True,
        check_company=True,
        help="The fiscal position determines the taxes/accounts used for this contact.",
    )

    @api.model
    def _commercial_fields(self):
        return super()._commercial_fields() + ["property_account_position_id"]

    def _check_vat(self, validation="error"):
        for partner in self:
            vat, _country_code = self._run_vat_checks(
                partner.commercial_partner_id.country_id,
                partner.vat,
                partner_name=partner.name,
                validation=validation,
            )
            if vat != partner.vat:
                partner.vat = vat

    @api.model
    def _run_vat_checks(self, country, vat, partner_name="", validation="error"):
        assert validation in (False, "error", "setnull")
        return vat, (country and country.code) or ""

    def _is_vat_required_valid(self, company=None):
        self.check_singleton()
        return bool(self.vat)
