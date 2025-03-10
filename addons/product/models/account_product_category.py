from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.translate import _


class AccountProductCategory(models.Model):
    _name = "account.product.category"
    _inherit = ["mail.thread"]
    _description = "Product Category"
    _parent_name = "parent_id"
    _parent_store = True
    _rec_name = "complete_name"
    _order = "complete_name"

    name = fields.Char(
        string="Name",
        required=True,
        index="trigram",
    )
    active = fields.Boolean(default=True)
    parent_id = fields.Many2one(
        comodel_name="account.product.category",
        string="Parent Category",
        index=True,
        ondelete="cascade",
    )
    parent_path = fields.Char(index=True)
    child_id = fields.One2many(
        comodel_name="account.product.category",
        inverse_name="parent_id",
        string="Child Categories",
    )
    complete_name = fields.Char(
        string="Complete Name",
        compute="_compute_complete_name",
        store=True,
        recursive=True,
    )
    count_product = fields.Integer(
        string="# Products",
        compute="_compute_count_product",
        help="The number of products under this category "
        "(Does not consider the children categories)",
    )
    product_properties_definition = fields.PropertiesDefinition("Product Properties")

    # ------------------------------------------------------------
    # CONSTRAINT METHODS
    # ------------------------------------------------------------

    @api.constrains("parent_id")
    def _check_category_recursion(self):
        if self._has_cycle():
            raise ValidationError(_("You cannot create recursive categories."))

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    def _compute_count_product(self):
        read_group_res = self.env["product.template"]._read_group(
            [("categ_id", "child_of", self.ids)],
            ["categ_id"],
            ["__count"],
        )
        group_data = {categ.id: count for categ, count in read_group_res}

        for categ in self:
            count_product = 0
            for sub_categ_id in categ.search([("id", "child_of", categ.ids)]).ids:
                count_product += group_data.get(sub_categ_id, 0)
            categ.count_product = count_product

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for category in self:
            if category.parent_id:
                category.complete_name = (
                    f"{category.parent_id.complete_name} / {category.name}"
                )
            else:
                category.complete_name = category.name

    @api.depends_context("hierarchical_naming")
    def _compute_display_name(self):
        if self.env.context.get("hierarchical_naming", True):
            return super()._compute_display_name()

        for category in self:
            category.display_name = category.name

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    @api.model
    def name_create(self, name):
        category = self.create({"name": name})
        return category.id, category.display_name
