from odoo.addons.documents_product.controllers.documents_document import (
    ProductDocumentsController,
)


class MRPProductDocumentController(ProductDocumentsController):
    def get_additional_create_params(self, **kwargs):
        super_values = super().get_additional_create_params(**kwargs)
        if kwargs.get("attached_on_bom"):
            return super_values | {"attached_on_mrp": "bom"}
        return super_values
