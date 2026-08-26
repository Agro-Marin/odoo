from odoo import _, api, fields, models
from odoo.fields import Command


class UpdateProductAttributeValue(models.TransientModel):
    _name = "update.product.attribute.value"
    _description = "Update product attribute value"

    attribute_value_id = fields.Many2one(
        comodel_name="product.attribute.value",
        required=True,
    )
    mode = fields.Selection(
        selection=[
            ("add", "Add to existing products"),
            ("update_extra_price", "Update the extra price on existing products"),
        ],
    )
    message = fields.Char(compute="_compute_message")
    product_count = fields.Integer(compute="_compute_product_count")

    @api.depends("product_count", "mode", "attribute_value_id")
    def _compute_message(self):
        self.message = ""
        for wizard in self:
            if wizard.mode == "add":
                wizard.message = _(
                    'You are about to add the value "%(attribute_value)s" to %(product_count)s products.',
                    attribute_value=wizard.attribute_value_id.name,
                    product_count=wizard.product_count,
                )
            elif wizard.mode == "update_extra_price":
                wizard.message = _(
                    "You are about to update the extra price of %s products.",
                    wizard.product_count,
                )

    def _get_product_count_key(self):
        self.ensure_one()
        if self.mode == "add":
            return ("add", self.attribute_value_id.attribute_id.id)
        if self.mode == "update_extra_price":
            return ("update_extra_price", self.attribute_value_id.id)
        return None

    @api.model
    def _get_product_count_domain(self, key):
        mode, record_id = key
        if mode == "add":
            return [("attribute_line_ids.attribute_id", "=", record_id)]
        return [("attribute_line_ids.value_ids", "=", record_id)]

    @api.depends("mode", "attribute_value_id")
    def _compute_product_count(self):
        self.product_count = 0
        ProductTemplate = self.env["product.template"]
        keys_by_wizard = {wizard: wizard._get_product_count_key() for wizard in self}
        counts = {
            key: ProductTemplate.search_count(self._get_product_count_domain(key))
            for key in set(keys_by_wizard.values()) - {None}
        }
        for wizard in self:
            wizard.product_count = counts.get(keys_by_wizard[wizard], 0)

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
                ("product_tmpl_id.company_id", "in", self.env.companies.ids + [False]),
            ]
        )
        ptals.write({"value_ids": [Command.link(self.attribute_value_id.id)]})

    def _update_extra_price_on_existing_products(self):
        ptavs = self.env["product.template.attribute.value"].search(
            [
                ("product_attribute_value_id", "=", self.attribute_value_id.id),
                ("product_tmpl_id.company_id", "in", self.env.companies.ids + [False]),
            ]
        )
        ptavs.write({"price_extra": self.attribute_value_id.default_extra_price})
