from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductCategory(models.Model):
    _name = "product.category"
    _inherit = ["mail.thread"]
    _description = "Product Category"
    _parent_name = "parent_id"
    _parent_store = True
    _rec_name = "complete_name"
    _order = "complete_name"

    name = fields.Char(string="Name", required=True, index="trigram")
    complete_name = fields.Char(
        string="Complete Name",
        compute="_compute_complete_name",
        store=True,
        recursive=True,
    )
    parent_id = fields.Many2one(
        comodel_name="product.category",
        string="Parent Category",
        # `restrict`, not `cascade`: a cascade would silently delete whole
        # subtrees at the SQL level (skipping the Python unlink hooks and mail
        # cleanup) and detach every product under them.
        ondelete="restrict",
        index=True,
    )
    parent_path = fields.Char(index=True)
    child_id = fields.One2many(
        comodel_name="product.category",
        inverse_name="parent_id",
        string="Child Categories",
    )
    product_count = fields.Integer(
        string="# Products",
        compute="_compute_product_count",
        help="The number of products under this category and its children.",
    )
    product_properties_definition = fields.PropertiesDefinition("Product Properties")

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for category in self:
            if category.parent_id:
                category.complete_name = "%s / %s" % (
                    category.parent_id.complete_name,
                    category.name,
                )
            else:
                category.complete_name = category.name

    def _compute_product_count(self):
        read_group_res = self.env["product.template"]._read_group(
            [("categ_id", "child_of", self.ids)], ["categ_id"], ["__count"]
        )
        # Attribute each counted category's products to all its ancestors in
        # `self`, derived from parent_path (O(count groups × depth)).
        self_ids = set(self.ids)
        count_by_categ = {}
        for categ, count in read_group_res:
            for ancestor_id in map(int, categ.parent_path.split("/")[:-1]):
                if ancestor_id in self_ids:
                    count_by_categ[ancestor_id] = (
                        count_by_categ.get(ancestor_id, 0) + count
                    )
        for categ in self:
            categ.product_count = count_by_categ.get(categ.id, 0)

    @api.constrains("parent_id")
    def _check_category_recursion(self):
        if self._has_cycle():
            raise ValidationError(_("You cannot create recursive categories."))

    @api.model
    def name_create(self, name):
        category = self.create({"name": name})
        return category.id, category.display_name

    @api.depends_context("hierarchical_naming")
    def _compute_display_name(self):
        if self.env.context.get("hierarchical_naming", True):
            return super()._compute_display_name()
        for record in self:
            record.display_name = record.name
        return None

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        if "name" not in default:
            for category, vals in zip(self, vals_list, strict=False):
                vals["name"] = _("%s (copy)", category.name)
        return vals_list
