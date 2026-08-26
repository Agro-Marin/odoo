from odoo.fields import Domain

from odoo.addons.portal.controllers import portal_thread


class PortalChatter(portal_thread.PortalChatter):
    # The "a body-less rating is still worth showing" rule used to be overridden
    # here. It now lives on `mixin.mail.thread._get_portal_message_non_empty_domain`,
    # which this controller's `_get_non_empty_message_domain` delegates to, so
    # the chatter is unchanged -- and the counters built on the same model
    # method (`website_slides.comments_count`) finally agree with what the
    # chatter displays instead of undercounting it by exactly those ratings.

    def _setup_portal_message_fetch_extra_domain(self, data):
        domain = super()._setup_portal_message_fetch_extra_domain(data)
        if data.get("rating_value", False) is not False:
            domain &= Domain("rating_value", "=", float(data["rating_value"]))
        return domain
