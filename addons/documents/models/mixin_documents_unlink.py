from odoo import models


class MixinDocumentsUnlink(models.AbstractModel):

    _name = "mixin.documents.unlink"
    _description = "Documents unlink mixin"

    def unlink(self) -> bool:
        documents = (
            self.env["documents.document"]
            .sudo()
            .search(
                [
                    ("res_model", "=", self._name),
                    ("res_id", "in", self.ids),
                    ("active", "=", True),
                ]
            )
        )
        if documents:
            documents.write({"res_model": False, "res_id": False})
            documents.action_archive()
        return super().unlink()
