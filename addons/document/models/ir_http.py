from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self) -> dict:
        res = super().session_info()
        res["groups"]["document.group_documents_manager"] = self.env.user.has_group(
            "document.group_documents_manager"
        )
        res["groups"]["document.group_documents_user"] = self.env.user.has_group(
            "document.group_documents_user"
        )
        res["groups"]["base.group_multi_company"] = self.env.user.has_group(
            "base.group_multi_company"
        )
        # The share, move, duplicate, shortcut and add-to-documents flows open
        # wizards that only document_enterprise ships; the client hides those
        # entry points rather than calling models that are not there.
        res["document_enterprise_actions"] = all(
            model in self.env for model in ("document.sharing", "document.operation")
        )
        return res
