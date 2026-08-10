from odoo import fields, models


class CredentialCredential(models.Model):
    """Extend credential.credential to support outbound endpoint linking."""

    _name = "credential.credential"
    _inherit = ["credential.credential", "mail.thread"]

    service_id = fields.Many2one(
        comodel_name="api.endpoint.outbound",
        string="Outbound Endpoint",
        index=True,
        ondelete="cascade",
        help="The outbound API endpoint this credential is associated with.",
    )
