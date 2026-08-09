from odoo import fields, models
from odoo.tools import groupby

from odoo.addons.mail.tools.discuss import Store


class MailMessageReaction(models.Model):
    _name = "mail.message.reaction"
    _description = "Message Reaction"
    _order = "id desc"
    _log_access = False

    message_id = fields.Many2one(
        string="Message",
        comodel_name="mail.message",
        ondelete="cascade",
        required=True,
        readonly=True,
        index=True,
    )
    content = fields.Char(string="Content", required=True, readonly=True)
    partner_id = fields.Many2one(
        string="Reacting Partner",
        comodel_name="res.partner",
        ondelete="cascade",
        readonly=True,
    )
    guest_id = fields.Many2one(
        string="Reacting Guest",
        comodel_name="mail.guest",
        ondelete="cascade",
        readonly=True,
    )

    _partner_unique = models.UniqueIndex(
        "(message_id, content, partner_id) WHERE partner_id IS NOT NULL"
    )
    _guest_unique = models.UniqueIndex(
        "(message_id, content, guest_id) WHERE guest_id IS NOT NULL"
    )

    _partner_or_guest_exists = models.Constraint(
        "CHECK((partner_id IS NOT NULL AND guest_id IS NULL) OR (partner_id IS NULL AND guest_id IS NOT NULL))",
        "A message reaction must be from a partner or from a guest.",
    )

    def _to_store(self, store: Store, fields):
        if fields:
            raise NotImplementedError("Fields are not supported for reactions.")
        # Every reactor in the batch, resolved once, purely to seed the prefetch
        # of the per-group sets below. ``union()`` returns a recordset whose
        # prefetch covers only its own group, so serializing a message with N
        # distinct reactions would read one reactor per group -- N round trips
        # for what is one set of partners. Prefetching over the whole batch lets
        # the first group's read cover every later one.
        all_partner_ids = self.partner_id._ids
        all_guest_ids = self.guest_id._ids
        for (message, content), reactions in groupby(
            self, lambda r: (r.message_id, r.content)
        ):
            reactions = self.env["mail.message.reaction"].union(*reactions)
            data = {
                "content": content,
                "count": len(reactions),
                "guests": Store.Many(
                    reactions.guest_id.with_prefetch(all_guest_ids),
                    ["avatar_128", "name"],
                ),
                "message": message.id,
                "partners": Store.Many(
                    reactions.partner_id.with_prefetch(all_partner_ids),
                    ["avatar_128", *message._get_store_partner_name_fields()],
                ),
                "sequence": min(reactions.ids),
            }
            store.add_model_values("MessageReactions", data)
