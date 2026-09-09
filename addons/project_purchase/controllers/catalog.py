from odoo.http import request, route

from odoo.addons.product.controllers.catalog import ProductCatalogController


class ProjectPurchaseCatalogController(ProductCatalogController):
    @route()
    def product_catalog_update_order_line_info(
        self, res_model, order_id, product_id, quantity=0, **kwargs
    ):
        if project_id := kwargs.get("project_id"):
            request.update_context(project_id=project_id)
        return super().product_catalog_update_order_line_info(
            res_model, order_id, product_id, quantity, **kwargs
        )
