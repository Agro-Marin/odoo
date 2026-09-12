from odoo import fields, models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class MixinFavorite(models.AbstractModel):
    _name = "mixin.favorite"
    _description = "Favorite Mixin"

    is_favorite = fields.Boolean(string="Favorite")

    def action_toggle_favorite(self) -> None:
        _debug.lifecycle("favorite_toggled", model=self._name, count=len(self))
        for record in self:
            record.is_favorite = not record.is_favorite
