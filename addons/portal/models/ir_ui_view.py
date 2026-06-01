from odoo import fields, models


class IrUiView(models.Model):
    """Surface the 'optional inheritance' toggle used by the website editor's view picker."""

    _inherit = "ir.ui.view"

    customize_show = fields.Boolean(
        "Show As Optional Inherit",
        default=False,
        help=(
            "When set, the website editor surfaces this view as a user-togglable "
            "inherited variant of its parent (used by the Customize panel)."
        ),
    )
