# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models


class MixinMailRender(models.AbstractModel):
    _inherit = "mixin.mail.render"

    @api.model
    def _shorten_links_text_skip_prefixes(self, base_url):
        """Never shorten this module's own unsubscribe page.

        ``/sms/<mailing_id>/<trace_code>`` is built by ``sms_composer`` and is the
        one link in an SMS that has to keep working; routing it through a tracker
        would put a redirect in front of it. ``link_tracker`` used to carry this
        prefix itself, in a module that does not depend on ``sms``.
        """
        return (*super()._shorten_links_text_skip_prefixes(base_url), base_url + '/sms/')
