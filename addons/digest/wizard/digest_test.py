from odoo import fields, models


class DigestTest(models.TransientModel):
    _name = "digest.test"
    _description = "Sample Digest Wizard"

    digest_id = fields.Many2one(
        "digest.digest", string="Digest", required=True, ondelete="cascade"
    )
    user_ids = fields.Many2many(
        "res.users",
        string="Recipients",
        domain=[("share", "=", False)],
        default=lambda self: self.env.user,
    )

    def send_mail_test(self):
        """Render the digest to the chosen recipients, once, right now.

        Two things separate a preview from `_action_send`: it writes only to the
        users picked here rather than to `digest_id.user_ids`, and it leaves the
        tips alone -- a tip is consumed once per user for good, so previewing a
        digest must not cost the reader a tip they never saw.
        """
        self.ensure_one()

        for user in self.user_ids:
            # same context `_action_send` builds: the header date and every
            # `format_*` in the body belong to the recipient, not to whoever
            # pressed Test. Without this the preview would render in the
            # sender's locale and misreport what the recipient will get.
            self.digest_id.with_context(
                lang=user.lang,
                tz=user.tz,
            )._action_send_to_user(user, consume_tips=False, force_send=True)
