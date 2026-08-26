from odoo import models
from odoo.fields import Domain


class MixinMailThread(models.AbstractModel):
    _inherit = "mixin.mail.thread"

    def _get_portal_message_non_empty_domain(self):
        """Keep body-less ratings visible in the portal chatter.

        A rating posted without a comment carries no body and no attachment, so
        the generic "non-empty" rule drops it — yet the star value *is* the
        content, and the chatter is meant to show it.

        This lives on the model, not on ``portal.controllers.portal_thread``
        where it used to. The controller-side hook only fed the chatter's own
        fetch, while ``mixin.mail.thread._get_portal_message_fetch_domain`` —
        the same rule, and the single source of truth the counters read — kept the
        stricter default. Anything counting what the chatter displays therefore
        disagreed with it by exactly the body-less ratings:
        ``website_slides.comments_count`` renders a badge next to a comment list
        that shows more items than the badge admits to. Overriding here fixes
        both at once, which is what having one definition was for.
        """
        return super()._get_portal_message_non_empty_domain() | Domain(
            "rating_value", "!=", False
        )
