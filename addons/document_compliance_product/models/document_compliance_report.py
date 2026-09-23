from odoo import api, models

# A product answers only to the types that name products: "all" types were
# written for partners, employees and assets, and would otherwise hold every
# product of the catalog to them. Within product types, one naming categories
# applies to products filed under any of them or their subcategories.
PRODUCT_SCOPE = """
    e.entity_type != 'product.template'
    OR (
        dt.applies_to = 'product.template'
        AND (
            NOT EXISTS (
                SELECT 1 FROM document_type_product_category_rel r
                 WHERE r.type_id = dt.id
            )
            OR EXISTS (
                SELECT 1
                  FROM document_type_product_category_rel r
                  JOIN product_category scope ON scope.id = r.categ_id
                  JOIN product_template product ON product.id = e.entity_id
                  JOIN product_category categ ON categ.id = product.categ_id
                 WHERE r.type_id = dt.id
                   AND categ.parent_path LIKE scope.parent_path || '%%'
            )
        )
    )
"""


class DocumentComplianceReport(models.Model):
    _inherit = "document.compliance.report"

    @api.model
    def _get_entity_model_map(self) -> dict[str, str]:
        return {
            **super()._get_entity_model_map(),
            "product.template": "product_template",
        }

    def _get_entity_name_column(self, model: str) -> str:
        # The product name is translated; en_US always holds the source value.
        if model == "product.template":
            return "name->>'en_US'"
        return super()._get_entity_name_column(model)

    def _get_type_scope_conditions(self) -> list[str]:
        return [*super()._get_type_scope_conditions(), PRODUCT_SCOPE]
