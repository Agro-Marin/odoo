from odoo import fields, models

EXCEPTION_KINDS = [
    ("self_approval", "Deciding one's own request"),
    ("requester_exclusion", "Approving a request made on one's behalf"),
]


class IrAccessException(models.Model):
    _inherit = "ir.access.exception"

    kind = fields.Selection(
        selection_add=EXCEPTION_KINDS,
        ondelete={kind: "cascade" for kind, _label in EXCEPTION_KINDS},
    )
