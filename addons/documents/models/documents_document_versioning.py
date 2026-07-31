"""Version history: every content replacement keeps what it replaced.

`write` files the outgoing attachment into `previous_attachment_ids`; this
is everything that then *reads* that history -- restoring a version,
deleting one, and capping how many are kept.
"""

from odoo import _, models
from odoo.exceptions import UserError


class DocumentsDocument(models.Model):
    _inherit = "documents.document"

    def action_delete_from_history(self, attachment_id: int) -> None:
        """Delete a version, promoting the newest remaining one if it was current.

        The write right was only ever enforced downstream, by
        ``ir.attachment.unlink`` and by the ``attachment_id`` write below, so a
        viewer's attempt surfaced as a raw ``AccessError`` naming an attachment
        they cannot see -- rather than this method's own wording, the way its
        twin :meth:`action_restore_version` states it.

        Deleting the *current* version silently swaps the document's content for
        an older one. That is the same content change ``action_restore_version``
        performs and logs; unlogged, "the file is not what it was yesterday and
        the chatter says nothing" was the only trace left.
        """
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
        """Make a previous version the current one again.

        Going back used to require *deleting* the current version -- the only
        code path that promoted an older attachment was
        `action_delete_from_history`, as a side effect, and it always promoted
        the newest one rather than a chosen one. So "revert to what we had on
        Tuesday" meant destroying everything since, one version at a time, and
        left no record that it had happened.

        Restoring is a content change like any other: the version being replaced
        goes into the history (`write` handles that), and the swap is logged.
        """
        self.ensure_one()
        self._check_access_or_raise(
            "write", _("You are not allowed to restore a version of this document.")
        )

        attachment = self.env["ir.attachment"].browse(attachment_id).exists()
        if attachment not in self.previous_attachment_ids:
            raise UserError(_("This version does not belong to this document."))

        replaced = self.attachment_id
        # `write` moves the outgoing attachment into the history and takes the
        # incoming one out of it, which is exactly the swap wanted here.
        self.write({"attachment_id": attachment.id})
        self.message_post(
            body=_(
                "Version restored: “%(restored)s” replaces “%(replaced)s”.",
                restored=attachment.name,
                replaced=replaced.name,
            )
        )

    def _prune_versions(self) -> None:
        """Drop the oldest versions beyond ``documents.max_versions``.

        Every content replacement keeps a full copy of what it replaced, and
        nothing ever removed them: a document edited daily grows a filestore
        blob a day, forever. The limit is opt-in (0, the default, keeps
        everything) because enabling it destroys data -- that has to be an
        administrator's decision, not something an upgrade does silently.
        """
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
                # sudo: pruning is bookkeeping on content the writer is already
                # replacing; the attachments hang off this document and may not
                # be individually writable by them.
                versions[max_versions:].sudo().unlink()
