from odoo import models


class CardCampaignTag(models.Model):
    _name = 'card.campaign.tag'
    _description = 'Marketing Card Campaign Tag'
    # `name` (translated, unique on the source term), `active`, `color` and
    # `code` come from the mixin, whose index replaces the `unique(name)`
    # constraint this model declared. Flat: campaign tags do not nest.
    _inherit = ['mixin.tag']
