# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models


class Base(models.AbstractModel):
    """Extend base model with HTML editor field attributes."""

    _inherit = 'base'

    @api.model
    def _get_view_field_attributes(self):
        """Add sanitize attributes to the list of view field attributes."""
        keys = super()._get_view_field_attributes()
        keys.append('sanitize')
        keys.append('sanitize_tags')
        return keys
