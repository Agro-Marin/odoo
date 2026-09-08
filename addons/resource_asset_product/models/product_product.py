from odoo import models


class ProductProduct(models.Model):
    """The variant half of the asset button.

    `_inherits` delegates fields to `product.template`, not methods, and the
    product.product form is a primary inheritor of the template form -- so a
    stat button added there is validated against `product.product`, which had
    no `action_view_assets` and made every upgrade that revalidated a
    product.product view fail to load the registry.
    """

    _inherit = "product.product"

    def action_view_assets(self):
        self.check_singleton()
        return self.product_tmpl_id.action_view_assets()
