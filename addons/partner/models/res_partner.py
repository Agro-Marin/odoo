from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.fields import Domain


class ResPartner(models.Model):
    _inherit = "res.partner"

    age = fields.Integer(
        compute="_compute_age",
        search="_search_age",
    )
    age_range_id = fields.Many2one(
        "res.partner.age.range",
        string="Age Range",
        compute="_compute_age_range_id",
        store=True,
        index="btree_not_null",
    )

    @api.depends("birthdate")
    def _compute_age(self) -> None:
        today = fields.Date.today()
        for partner in self:
            partner.age = (
                relativedelta(today, partner.birthdate).years
                if partner.birthdate
                else False
            )

    @api.model
    def _latest_birthdate_for_age(self, age):
        """The newest birthdate that has already completed ``age`` years."""
        return fields.Date.today() - relativedelta(years=age)

    @api.model
    def _search_age(self, operator, value):
        if operator not in ("<", "<=", ">", ">=", "=", "!="):
            raise NotImplementedError(
                self.env._(
                    "Unsupported operator %(operator)s on age.", operator=operator
                )
            )
        if not isinstance(value, int):
            raise ValueError(self.env._("Age is searched by a whole number of years."))

        at_least = self._latest_birthdate_for_age(value)
        over = self._latest_birthdate_for_age(value + 1)

        if operator == ">=":
            return Domain("birthdate", "<=", at_least)
        if operator == ">":
            return Domain("birthdate", "<=", over)
        if operator == "<":
            return Domain("birthdate", ">", at_least)
        if operator == "<=":
            return Domain("birthdate", ">", over)
        exactly = Domain("birthdate", ">", over) & Domain("birthdate", "<=", at_least)
        return (
            exactly if operator == "=" else ~exactly & Domain("birthdate", "!=", False)
        )

    @api.depends("birthdate")
    def _compute_age_range_id(self) -> None:
        age_ranges = self.env["res.partner.age.range"].search([])
        for partner in self:
            if partner.birthdate:
                age_range = age_ranges.filtered(
                    lambda age_range, partner=partner: age_range._covers(
                        partner.birthdate.year
                    )
                )[:1]
            else:
                age_range = self.env["res.partner.age.range"].browse()
            if partner.age_range_id != age_range:
                partner.age_range_id = age_range

    def _get_backend_root_menu_ids(self):
        return super()._get_backend_root_menu_ids() + [
            self.env.ref("partner.partner_menu_root").id
        ]
