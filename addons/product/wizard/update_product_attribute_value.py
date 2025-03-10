# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.fields import Command


class UpdateProductAttributeValue(models.TransientModel):
    _name = "update.product.attribute.value"
    _description = "Update product attribute value"

    attribute_value_id = fields.Many2one("product.attribute.value", required=True)
    mode = fields.Selection(
        selection=[
            ("add", "Add to existing products"),
            ("update_extra_price", "Update the extra price on existing products"),
        ]
    )
    message = fields.Char(compute="_compute_message")
    count_product = fields.Integer(compute="_compute_count_product")

    @api.depends("count_product", "mode", "attribute_value_id")
    def _compute_message(self):
        self.message = ""
        for wizard in self:
            if wizard.mode == "add":
                wizard.message = _(
                    'You are about to add the value "%(attribute_value)s" to %(count_product)s products.',
                    attribute_value=wizard.attribute_value_id.name,
                    count_product=wizard.count_product,
                )
            elif wizard.mode == "update_extra_price":
                wizard.message = _(
                    "You are about to update the extra price of %s products.",
                    wizard.count_product,
                )

    @api.depends("mode")
    def _compute_count_product(self):
        self.count_product = 0
        ProductTemplate = self.env["product.template"]
        for wizard in self:
            if wizard.mode == "add":
                wizard.count_product = ProductTemplate.search_count(
                    [
                        (
                            "attribute_line_ids.attribute_id",
                            "=",
                            wizard.attribute_value_id.attribute_id.id,
                        ),
                    ]
                )
            elif wizard.mode == "update_extra_price":
                wizard.count_product = ProductTemplate.search_count(
                    [
                        (
                            "attribute_line_ids.value_ids",
                            "=",
                            wizard.attribute_value_id.id,
                        ),
                    ]
                )

    def action_confirm(self):
        self.ensure_one()
        if self.mode == "add":
            self._add_value_to_existing_attribute_lines()
        elif self.mode == "update_extra_price":
            self._update_extra_price_on_existing_products()

    def _add_value_to_existing_attribute_lines(self):
        ptals = self.env["product.template.attribute.line"].search(
            [
                ("attribute_id", "=", self.attribute_value_id.attribute_id.id),
                # Make sure we do not impact products belonging to other companies
                ("product_tmpl_id.company_id", "in", self.env.companies.ids + [False]),
            ]
        )
        ptals.write({"value_ids": [Command.link(self.attribute_value_id.id)]})

    def _update_extra_price_on_existing_products(self):
        ptavs = self.env["product.template.attribute.value"].search(
            [
                ("product_attribute_value_id", "=", self.attribute_value_id.id),
                # Make sure we do not impact products belonging to other companies
                ("product_tmpl_id.company_id", "in", self.env.companies.ids + [False]),
            ]
        )
        ptavs.write({"price_extra": self.attribute_value_id.default_extra_price})
