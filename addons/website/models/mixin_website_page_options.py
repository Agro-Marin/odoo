# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import fields, models

logger = logging.getLogger(__name__)


class MixinWebsitePageOptions(models.AbstractModel):
    _name = "mixin.website.page_options"
    _inherit = ["mixin.website.page_visibility_options"]
    _description = "Website page/record specific options"

    header_overlay = fields.Boolean()
    header_color = fields.Char()
    header_text_color = fields.Char()
