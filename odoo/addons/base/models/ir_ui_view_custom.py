from odoo import fields, models


class IrUiViewCustom(models.Model):
    """Per-user Copy-on-Write override of a parent view's arch (dashboards)."""

    _name = "ir.ui.view.custom"
    _description = "Custom View"
    _order = "create_date desc, id desc"  # search(limit=1) should return the last customization
    _rec_name = "user_id"
    _allow_sudo_commands = False

    # Keeps its own single-column index: the composite (user_id, ref_id) index
    # cannot serve the `ref_id IN (...)` lookup in ir.ui.view.write (no user_id prefix).
    ref_id = fields.Many2one(
        "ir.ui.view",
        string="Original View",
        index=True,
        required=True,
        ondelete="cascade",
    )
    # No index=True: the composite (user_id, ref_id) index covers user-prefixed lookups
    # and the ondelete cascade reverse-lookup.
    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        ondelete="cascade",
    )
    arch = fields.Text(string="View Architecture", required=True)

    _user_id_ref_id = models.Index("(user_id, ref_id)")
