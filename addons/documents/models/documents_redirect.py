from odoo import api, fields, models


class DocumentsRedirect(models.Model):

    _name = "documents.redirect"
    _description = "Document Redirect"
    _log_access = False

    access_token = fields.Char(required=True, index="btree")
    document_id = fields.Many2one("documents.document", ondelete="cascade")

    @api.model
    def _get_redirection(self, access_token: str) -> models.Model:
        return self.search(
            [
                ("access_token", "=", access_token),
                ("document_id.access_via_link", "=", "view"),
            ],
            limit=1,
        ).document_id
