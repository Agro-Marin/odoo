from odoo import models
from odoo.tools import is_html_empty, lazy


class IrQweb(models.AbstractModel):
    """Inject portal-layout helpers (``is_html_empty``, ``frontend_languages``) into QWeb's frontend env."""

    _inherit = "ir.qweb"

    def _prepare_frontend_environment(self, values):
        """Augment the QWeb frontend env with helpers required by the portal layout template.

        Adds ``is_html_empty`` (used to hide empty rich-text blocks) and a lazy
        ``frontend_languages`` accessor (loaded only when the layout actually
        renders the language switcher). Also copies any leftover context keys
        into ``values`` so they remain accessible in the templates.
        """
        irQweb = super()._prepare_frontend_environment(values)
        # The `lazy(lambda: ...)` wrapper defers `_get_frontend()` until the
        # template actually reads `frontend_languages`. Inlining the call
        # (which is what PLW0108 suggests) would run a DB query on every
        # portal page render even when the language switcher is not displayed.
        values.update(
            is_html_empty=is_html_empty,
            frontend_languages=lazy(lambda: irQweb.env["res.lang"]._get_frontend()),  # noqa: PLW0108
        )
        for key in irQweb.env.context:
            if key not in values:
                values[key] = irQweb.env.context[key]

        return irQweb
