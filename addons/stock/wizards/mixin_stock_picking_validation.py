from odoo import fields, models
from odoo.tools.misc import clean_context

from ..tools import debug_log as dbg


class MixinStockPickingValidation(models.AbstractModel):
    _name = "mixin.stock.picking.validation"
    _description = "Interrupted Transfer Validation"

    validate_picking_ids = fields.Json(readonly=True)
    validate_kwargs = fields.Json(readonly=True)

    def _get_pickings_to_validate(self):
        return self.env["stock.picking"].browse(self.validate_picking_ids or ())

    def _resume_validation(self, pickings=None, **decisions):
        if pickings is None:
            pickings = self._get_pickings_to_validate()
        if not pickings:
            return True
        validate_kwargs = {**(self.validate_kwargs or {}), **decisions}
        dbg.pipeline.debug(
            "%s resumes validation of %s with %s",
            self._name,
            dbg.rec(pickings),
            validate_kwargs,
        )
        return pickings.with_context(clean_context(self.env.context)).button_validate(
            **validate_kwargs
        )
