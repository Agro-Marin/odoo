from odoo import models

from odoo.addons.mail.tools.discuss import Store


class ResUsers(models.Model):
    """User model extended with documents store data."""

    _inherit = "res.users"

    def _init_store_data(self, store: Store) -> None:
        super()._init_store_data(store)
        has_group = self.env.user.has_group("documents.group_documents_user")
        store.add_global_values(hasDocumentsUserGroup=has_group)
