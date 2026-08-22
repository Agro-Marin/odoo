from odoo import _, models
from odoo.exceptions import UserError


class DocumentsDocument(models.Model):
    _inherit = "documents.document"

    def action_delete_from_history(self, attachment_id: int) -> None:
        self.ensure_one()
        self._check_access_or_raise(
            "write", _("You are not allowed to delete a version of this document.")
        )
        attachment = self.env["ir.attachment"].browse(attachment_id)

        if attachment not in self.previous_attachment_ids and (
            attachment != self.attachment_id or not self.previous_attachment_ids
        ):
            raise UserError(_("You cannot delete this attachment."))

        deleted_name = attachment.name
        if attachment == self.attachment_id:
            promoted = max(
                self.previous_attachment_ids, key=lambda a: (a.create_date, a.id)
            )
            self.attachment_id = promoted
            self.message_post(
                body=_(
                    "Version deleted: “%(deleted)s” removed, “%(promoted)s” is now "
                    "the current version.",
                    deleted=deleted_name,
                    promoted=promoted.name,
                )
            )
        else:
            self.message_post(
                body=_("Version deleted from the history: “%s”.", deleted_name)
            )

        attachment.unlink()

    def action_restore_version(self, attachment_id: int) -> None:
        self.ensure_one()
        self._check_access_or_raise(
            "write", _("You are not allowed to restore a version of this document.")
        )

        attachment = self.env["ir.attachment"].browse(attachment_id).exists()
        if attachment not in self.previous_attachment_ids:
            raise UserError(_("This version does not belong to this document."))

        replaced = self.attachment_id
        self.write({"attachment_id": attachment.id})
        self.message_post(
            body=_(
                "Version restored: “%(restored)s” replaces “%(replaced)s”.",
                restored=attachment.name,
                replaced=replaced.name,
            )
        )

    def _prune_versions(self) -> None:
        max_versions = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param_int("documents.max_versions", 0)
        )
        if max_versions <= 0:
            return
        for document in self:
            versions = document.previous_attachment_ids.sorted(
                key=lambda attachment: (attachment.create_date, attachment.id),
                reverse=True,
            )
            if len(versions) > max_versions:
                versions[max_versions:].sudo().unlink()
