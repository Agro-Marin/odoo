from odoo import fields, models


class MixinFavorite(models.AbstractModel):
    _name = "mixin.favorite"
    _description = "Favorite Mixin"

    is_favorite = fields.Boolean(string="Favorite")

    def action_toggle_favorite(self) -> None:
        for record in self:
            record.is_favorite = not record.is_favorite
