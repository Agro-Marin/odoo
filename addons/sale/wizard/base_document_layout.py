from odoo import models


class BaseDocumentLayout(models.TransientModel):
    """Extends the 'base.document.layout' model to customize document layout previews for sales orders.

    This module provides a preview template for sales order quotations and ensures the correct
    rendering of document layouts based on the context of the active sales order."""

    _inherit = "base.document.layout"

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _get_preview_template(self):
        if self.env.context.get(
            "active_model"
        ) == "sale.order" and self.env.context.get("active_id"):
            return "sale.quote_document_layout_preview"

        return super()._get_preview_template()

    def _get_render_information(self, styles):
        res = super()._get_render_information(styles)

        if self.env.context.get(
            "active_model"
        ) == "sale.order" and self.env.context.get("active_id"):
            res["doc"] = self.env["sale.order"].browse(
                self.env.context.get("active_id")
            )

        return res
