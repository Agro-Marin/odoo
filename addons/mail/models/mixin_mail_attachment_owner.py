from collections.abc import Collection
from typing import Self

from odoo import api, models
from odoo.api import ValuesType
from odoo.fields import Command


class MixinMailAttachmentOwner(models.AbstractModel):
    _name = "mixin.mail.attachment.owner"
    _description = "Mail Attachment Ownership Mixin"

    @api.model
    def _get_linked_attachment_ids(self, vals_list: list[ValuesType]) -> set[int]:
        linked = set()
        for vals in vals_list:
            commands = vals.get("attachment_ids") or ()
            if not isinstance(commands, (list, tuple)):
                continue
            for command in commands:
                if isinstance(command, int):
                    linked.add(command)
                elif not isinstance(command, (list, tuple)) or not command:
                    continue
                elif command[0] == Command.LINK and len(command) > 1:
                    linked.add(command[1])
                elif command[0] == Command.SET and len(command) > 2:
                    linked.update(command[2] or ())
        return linked

    def _update_attachment_ownership(self, linked_ids: Collection[int] = ()) -> Self:
        linked_ids = set(linked_ids)
        for record in self:
            foreign = record.attachment_ids.filtered(
                lambda attachment, record=record: (
                    attachment.res_model != record._name
                    or attachment.res_id != record.id
                )
            )
            if not foreign:
                continue
            owned_elsewhere = foreign.filtered(
                lambda attachment: (
                    attachment.id in linked_ids
                    and attachment.res_model
                    and attachment.res_id
                )
            )
            if adoptable := foreign - owned_elsewhere:
                adoptable.write({"res_model": record._name, "res_id": record.id})
            if owned_elsewhere:
                copies = owned_elsewhere.copy(
                    default={"res_model": record._name, "res_id": record.id}
                )
                record.attachment_ids = (
                    record.attachment_ids - owned_elsewhere
                ) | copies
        return self
