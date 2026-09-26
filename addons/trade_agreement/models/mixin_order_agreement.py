from odoo import api, fields, models
from odoo.fields import Command
from odoo.libs.debug_log import DebugLog

from odoo.addons.trade.tools import direction_of

_debug = DebugLog(__name__)


class MixinOrderAgreement(models.AbstractModel):
    _name = "mixin.order.agreement"
    _description = "Order Placed Against an Agreement"

    @api.onchange("agreement_id")
    def _onchange_agreement_id(self):
        agreement = self.agreement_id
        if not agreement:
            return
        self = self.with_company(self.company_id)
        direction = direction_of(self)
        partner = self.partner_id or agreement.partner_id
        fiscal_position = (
            self.env["account.fiscal.position"]
            .with_company(self.company_id)
            ._get_fiscal_position(partner)
        )
        self.partner_id = partner.id
        self.fiscal_position_id = fiscal_position.id
        self.payment_term_id = partner[direction.partner_payment_term_field].id
        self.company_id = agreement.company_id.id
        self.currency_id = agreement.currency_id.id
        origins = self.origin.split(", ") if self.origin else []
        if agreement.name not in origins:
            self.origin = ", ".join([*origins, agreement.name])
        self.notes = agreement.description
        self.date_order = (
            max(
                fields.Datetime.now(), fields.Datetime.to_datetime(agreement.date_start)
            )
            if agreement.date_start
            else fields.Datetime.now()
        )
        if self.state != "draft":
            return
        _debug.logic(
            "order_filled_from_agreement",
            agreement=agreement,
            lines=len(agreement.line_ids),
        )
        self.line_ids = [
            Command.create(
                line._prepare_order_line_values(
                    product_qty=(
                        0.0
                        if agreement.agreement_type == "blanket_order"
                        else line.product_qty
                    ),
                    tax_ids=fiscal_position.map_tax(
                        line.product_id[direction.product_taxes_field].filtered(
                            lambda tax: any(
                                tax._serves_company(company)
                                for company in agreement.company_id.parent_ids
                            )
                        )
                    ).ids,
                )
            )
            for line in agreement.line_ids
        ]

    def _post_agreement_link(self, edit=False):
        for order in self.filtered("agreement_id"):
            order.message_post_with_source(
                "mail.message_origin_link",
                render_values={
                    "self": order,
                    "origin": order.agreement_id,
                    "edit": edit,
                },
                subtype_xmlid="mail.mt_note",
            )

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._post_agreement_link()
        return orders

    def write(self, vals):
        result = super().write(vals)
        if vals.get("agreement_id"):
            self._post_agreement_link(edit=True)
        return result
