import logging

from odoo import fields, models

logger = logging.getLogger(__name__)


class MixinWebsitePageVisibilityOptions(models.AbstractModel):
    _name = "mixin.website.page_visibility_options"
    _description = "Website page/record specific visibility options"

    header_visible = fields.Boolean(default=True)
    footer_visible = fields.Boolean(default=True)
