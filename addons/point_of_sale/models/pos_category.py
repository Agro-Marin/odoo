import random

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class PosCategory(models.Model):
    _name = "pos.category"
    _description = "Point of Sale Category"
    _inherit = ["mixin.pos.load"]
    _order = "sequence, name"

    @api.constrains("parent_id")
    def _check_category_recursion(self):
        if self._has_cycle():
            raise ValidationError(_("Error! You cannot create recursive categories."))

    def _default_color(self):
        return random.randint(0, 10)

    name = fields.Char(string="Category Name", required=True, translate=True)
    parent_id = fields.Many2one("pos.category", string="Parent Category", index=True)
    child_ids = fields.One2many(
        "pos.category", "parent_id", string="Children Categories"
    )
    sequence = fields.Integer(
        help="Gives the sequence order when displaying a list of product categories."
    )
    image_512 = fields.Image("Image", max_width=512, max_height=512)
    image_128 = fields.Image(
        "Image 128", related="image_512", max_width=128, max_height=128, store=True
    )
    color = fields.Integer("Color", required=False, default=_default_color)
    hour_until = fields.Float(
        string="Availability Until",
        default=24.0,
        help="The product will be available until this hour for online order and self order.",
    )
    hour_after = fields.Float(
        string="Availability After",
        default=0.0,
        help="The product will be available after this hour for online order and self order.",
    )

    has_image = fields.Boolean(compute="_compute_has_image")
    product_count = fields.Integer(compute="_compute_product_count")

    @api.model
    def _load_pos_data_domain(self, data, config):
        domain = []
        if config.limit_categories:
            preparation_categories = [
                printer["product_categories_ids"] for printer in data["pos.printer"]
            ]
            flattened_preparation_categories = [
                item for sublist in preparation_categories for item in sublist
            ]
            domain += [
                (
                    "id",
                    "in",
                    flattened_preparation_categories
                    + config.iface_available_categ_ids.ids,
                )
            ]
        return domain

    @api.model
    def _load_pos_data_fields(self, config):
        return [
            "id",
            "name",
            "parent_id",
            "child_ids",
            "write_date",
            "has_image",
            "color",
            "sequence",
            "hour_until",
            "hour_after",
        ]

    def _get_hierarchy(self) -> list[str]:
        self.check_singleton()
        return (self.parent_id._get_hierarchy() if self.parent_id else []) + [
            (self.name or "")
        ]

    @api.depends("parent_id")
    def _compute_display_name(self):
        for cat in self:
            cat.display_name = " / ".join(cat._get_hierarchy())

    def _get_blocking_pos_session(self, include_printers=False):
        """Return an open session whose register loads one of these categories.

        A register with `limit_categories` off loads every category, so it
        blocks whatever the ids are -- which is also what makes an uncategorised
        product blocked by such a register.

        `include_printers` additionally catches a category a preparation printer
        routes to: relevant when deleting the category itself, because the
        printer configuration would be left pointing at nothing, but not when
        archiving a product, which no printer references.
        """
        domain = [
            ("state", "!=", "closed"),
            ("company_id", "in", self.env.companies.ids),
        ]
        arms = [
            ("config_id.limit_categories", "=", False),
            ("config_id.iface_available_categ_ids", "in", self.ids),
        ]
        if include_printers:
            arms.append(
                ("config_id.printer_ids.product_categories_ids", "in", self.ids)
            )
        domain += ["|"] * (len(arms) - 1) + arms
        return self.env["pos.session"].sudo().search(domain, limit=1)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_session_open(self):
        blocking_session = self._get_blocking_pos_session(include_printers=True)
        if blocking_session:
            raise UserError(
                _(
                    "You cannot delete a point of sale category while the session"
                    " %(session)s of %(config)s is still opened.",
                    session=blocking_session.name,
                    config=blocking_session.config_id.name,
                )
            )

    @api.depends("image_128")
    def _compute_has_image(self):
        for category in self:
            category.has_image = bool(category.image_128)

    def _compute_product_count(self):
        descendants = {category: category._get_descendants() for category in self}
        all_descendants = self.browse().union(*descendants.values())
        products_by_category = dict(
            self.env["product.template"]._read_group(
                [("pos_categ_ids", "in", all_descendants.ids)],
                ["pos_categ_ids"],
                ["id:array_agg"],
            )
        )
        for category in self:
            # A product filed under both a parent and one of its children must
            # count once, hence the set rather than a sum of counts.
            products = set()
            for descendant in descendants[category]:
                products.update(products_by_category.get(descendant, []))
            category.product_count = len(products)

    def action_open_associated_products(self):
        self.check_singleton()
        action = self.env["ir.actions.act_window"]._get_action_dict_by_xml_id(
            "point_of_sale.product_template_action_pos_product"
        )
        context = action.get("context", {})
        if isinstance(context, str):
            context = self.env["ir.actions.actions"]._eval_action_context(context)
        action["context"] = {
            **context,
            "search_default_pos_categ_ids": [self.id],
            "default_pos_categ_ids": [self.id],
        }
        return action

    def _get_descendants(self):
        available_categories = self
        for child in self.child_ids:
            available_categories |= child
            available_categories |= child._get_descendants()
        return available_categories

    @api.constrains("hour_until", "hour_after")
    def _check_hour(self):
        for category in self:
            if not 0.0 <= category.hour_until <= 24.0:
                raise ValidationError(
                    _("The Availability Until must be set between 00:00 and 24:00")
                )
            if not 0.0 <= category.hour_after <= 24.0:
                raise ValidationError(
                    _("The Availability After must be set between 00:00 and 24:00")
                )
            if category.hour_until < category.hour_after:
                raise ValidationError(
                    _("The Availability Until must be greater than Availability After.")
                )
