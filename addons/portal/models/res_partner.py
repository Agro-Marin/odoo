from odoo import api, models
from odoo.fields import Domain


class ResPartner(models.Model):

    _inherit = "res.partner"

    @api.model
    def _get_fields_frontend_writable(self):
        return {
            "name",
            "phone",
            "email",
            "street",
            "street2",
            "city",
            "state_id",
            "country_id",
            "zip",
            "vat",
            "company_name",
        }

    def _can_edit_country(self):
        self.ensure_one()
        return True

    def can_edit_vat(self):
        self.ensure_one()
        return not self.parent_id

    def _can_be_edited_by_current_customer(self, **kwargs):
        self.ensure_one()
        return bool(self._filter_editable_by_current_customer(**kwargs))

    def _filter_editable_by_current_customer(self, **kwargs):
        if not self:
            return self
        current_partner = self._get_current_partner(**kwargs)
        editable = self & current_partner
        candidates = self - current_partner
        if candidates:
            editable |= self.env["res.partner"].search(
                [
                    ("id", "in", candidates.ids),
                    ("id", "child_of", current_partner.commercial_partner_id.id),
                    ("type", "in", ("invoice", "delivery", "other")),
                ]
            )
        return editable

    @api.model
    def _get_current_partner(self, **kwargs):
        if self.env.user._is_public():
            return self.env["res.partner"]
        return self.env.user.partner_id

    def _get_billing_address_domain(self):
        return Domain(
            [
                ("id", "child_of", self.ids),
                "|",
                ("type", "in", ["invoice", "other"]),
                ("id", "=", self.id),
            ]
        )

    def _get_delivery_address_domain(self):
        return Domain(
            [
                ("id", "child_of", self.ids),
                "|",
                ("type", "in", ["delivery", "other"]),
                ("id", "=", self.id),
            ]
        )
