from odoo import models
from odoo.http import request

from odoo.addons.mail.tools.discuss import Store


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        """Override to add the current user data (partner or guest) if applicable."""
        result = super().session_info()
        store = Store()
        ResUsers = self.env["res.users"]
        if cids := request.cookies.get("cids", False):
            # Tolerate a corrupted cookie (e.g. "cids=undefined"): a bare
            # int(cid) would raise ValueError and 500 every page load until the
            # cookie is cleared by hand. Skip non-numeric parts instead.
            allowed_company_ids = [
                company_id
                for company_id in (int(cid) for cid in cids.split("-") if cid.isdigit())
                if company_id in self.env.user.company_ids.ids
            ]
            ResUsers = self.with_context(allowed_company_ids=allowed_company_ids).env[
                "res.users"
            ]
        ResUsers._init_store_data(store)
        result["storeData"] = store.get_result()
        guest = self.env["mail.guest"]._get_guest_from_context()
        if not request.session.uid and guest:
            user_context = {"lang": guest.lang}
            result["user_context"] = user_context
        return result
