from odoo import api, fields, models


class ResCompany(models.Model):
    _name = "res.company"
    _inherit = ["res.company", "mixin.pos.load"]

    point_of_sale_config_id = fields.Many2one(
        comodel_name="point_of_sale.config",
        compute="_compute_point_of_sale_config_id",
        search="_search_point_of_sale_config_id",
    )

    point_of_sale_use_ticket_qr_code = fields.Boolean(
        related="point_of_sale_config_id.point_of_sale_use_ticket_qr_code",
    )
    point_of_sale_ticket_unique_code = fields.Boolean(
        related="point_of_sale_config_id.point_of_sale_ticket_unique_code",
    )
    point_of_sale_ticket_portal_url_display_mode = fields.Selection(
        related="point_of_sale_config_id.point_of_sale_ticket_portal_url_display_mode",
    )

    def _search_point_of_sale_config_id(self, operator, value):
        return self._search_config_link("point_of_sale.config", operator, value)

    def _compute_point_of_sale_config_id(self):
        self._compute_config_link("point_of_sale_config_id")

    @api.model
    def _load_pos_data_domain(self, data, config):
        return [("id", "=", config.company_id.id)]

    @api.model
    def _load_pos_data_fields(self, config):
        return [
            "id",
            "currency_id",
            "email",
            "website",
            "company_registry",
            "vat",
            "name",
            "phone_ids",
            "partner_id",
            "country_id",
            "state_id",
            "street",
            "city",
            "zip",
            "tax_calculation_rounding_method",
            "account_fiscal_country_id",
            "nomenclature_id",
            "point_of_sale_use_ticket_qr_code",
            "point_of_sale_ticket_unique_code",
            "point_of_sale_ticket_portal_url_display_mode",
        ]
