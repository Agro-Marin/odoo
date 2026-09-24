from odoo import fields, models
from odoo.libs.debug_log import DebugLog
from odoo.tools.misc import clean_context

_debug = DebugLog(__name__)


class StockWarnInsufficientQtyScrap(models.TransientModel):
    _name = "stock.warn.insufficient.qty.scrap"
    _inherit = ["mixin.stock.warn.insufficient.qty"]
    _description = "Warn Insufficient Scrap Quantity"

    scrap_id = fields.Many2one(comodel_name="stock.scrap")

    def _get_reference_document_company_id(self):
        return self.scrap_id.company_id

    def action_done(self):
        _debug.pipeline("insufficient_qty_confirmed", scrap=self.scrap_id.id)
        return self.with_context(
            clean_context(self.env.context)
        ).scrap_id._action_done()

    def action_cancel(self):
        if self.env.context.get("not_unlink_on_discard"):
            return True
        scrap = self.scrap_id
        if not scrap or scrap.state != "draft":
            return True
        scrap.check_access("write")
        _debug.lifecycle("insufficient_qty_cancelled", scrap=scrap.id)
        return scrap.sudo().unlink()
