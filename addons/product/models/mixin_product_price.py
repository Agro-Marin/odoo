from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class MixinProductPrice(models.AbstractModel):

    _name = "mixin.product.price"
    _description = "Product Pricing Mixin"

    def _check_price_uom(self, uom):
        self.ensure_one()
        if uom and self.uom_id and not self.uom_id._has_common_reference(uom):
            raise UserError(
                self.env._(
                    "The price of %(product)s cannot be expressed in %(unit)s:"
                    " that unit is not compatible with the product's unit"
                    " %(product_unit)s.",
                    product=self.display_name,
                    unit=uom.display_name,
                    product_unit=self.uom_id.display_name,
                )
            )

    def _convert_price_to_uom(self, price, uom):
        self._check_price_uom(uom)
        return self.uom_id._compute_price(price, uom)

    def _convert_price_from_uom(self, price, uom):
        self._check_price_uom(uom)
        return uom._compute_price(price, self.uom_id)

    @api.onchange("standard_price")
    def _onchange_standard_price(self):
        if self.standard_price < 0:
            raise ValidationError(
                self.env._("The cost of a product can't be negative.")
            )

    def _compute_price(
        self, price_type, uom=None, currency=None, company=None, date=False
    ):
        company = company or self.env.company
        date = date or fields.Date.context_today(self)

        records = self.with_company(company)
        if price_type == "standard_price":
            records = records.sudo()

        prices = dict.fromkeys(records.ids, 0.0)
        for record in records:
            price = record._get_price_base(price_type)
            if price_type == "list_price":
                price += record._get_attributes_extra_price()

            if uom:
                price = record._convert_price_to_uom(price, uom)

            if currency:
                price = record._get_price_currency(price_type)._convert(
                    price, currency, company, date
                )

            prices[record.id] = price
        return prices

    def _get_price_base(self, price_type):
        self.ensure_one()
        return self[price_type] or 0.0

    def _get_price_currency(self, price_type):
        self.ensure_one()
        if price_type == "standard_price":
            return self.cost_currency_id
        return self.currency_id

    def _get_attributes_extra_price(self):
        self.ensure_one()
        return 0.0
