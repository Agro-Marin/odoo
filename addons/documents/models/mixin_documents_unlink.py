from odoo import models


class MixinDocumentsUnlink(models.AbstractModel):
    """Send the related documents to trash when the record is deleted."""

    _name = "mixin.documents.unlink"
    _description = "Documents unlink mixin"

    def unlink(self) -> bool:
        """Prevent deletion of the attachments / documents and send them to the trash instead."""
        # Search/write in sudo: the record being deleted may have linked
        # documents its deleter cannot access (restricted membership), and a
        # non-sudo search would miss them, leaving a document dangling on a
        # res_model/res_id whose record no longer exists.
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
            # Go through `action_archive` rather than writing `active = False`
            # directly: the trash log message, the deletion-date chatter and the
            # `_raise_if_used_folder` check all live there.
            documents.action_archive()
        return super().unlink()
