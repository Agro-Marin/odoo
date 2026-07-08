# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models


class ResCompany(models.Model):
    _inherit = "res.company"

    def _create_unbuild_sequence(self):
        return self.env["ir.sequence"].create(
            [
                {
                    "name": "Unbuild",
                    "code": "mrp.unbuild",
                    "company_id": company.id,
                    "prefix": "UB/",
                    "padding": 5,
                    "number_next": 1,
                    "number_increment": 1,
                }
                for company in self
            ],
        )

    @api.model
    def create_missing_unbuild_sequences(self):
        having = (
            self.env["ir.sequence"]
            .search([("code", "=", "mrp.unbuild")])
            .mapped("company_id")
        )
        self._companies_without(having)._create_unbuild_sequence()

    def _create_per_company_sequences(self):
        super()._create_per_company_sequences()
        self._create_unbuild_sequence()
