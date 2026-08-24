from collections.abc import Collection

from odoo import models

from odoo.addons.mail.tools.recipients import RecipientData


class MailFollowers(models.Model):
    _inherit = "mail.followers"

    def _get_recipient_data(
        self,
        records: models.BaseModel | None,
        message_type: str,
        subtype_id: int,
        pids: Collection[int] = (),
        *,
        include_followers: bool = True,
    ) -> dict[int, dict[int, RecipientData]]:
        """Deliver by SMS to the partners the SMS was actually addressed to.

        Only the explicitly named recipients: following a record does not sign
        anyone up for text messages, and `_message_sms` derives `partner_ids`
        from the record's own number field before it posts.

        There used to be a third branch here, taken when `pids` was `None`
        rather than empty, which marked every partner in `_mail_get_partners()`.
        Nothing could reach it: `_notify_get_recipients` always passes a list,
        `_message_post_batch_follower_data` passes `[]`, and the two callers
        that pass `None` never pass `message_type='sms'`. It also asked the base
        method for a distinction the base does not keep -- `_get_recipient_data`
        normalises `pids` with `list(pids or [])`, so `None` and `[]` are one
        value by the time it runs, and an override reading them apart is reading
        something that is not there.
        """
        recipients_data = super()._get_recipient_data(
            records,
            message_type,
            subtype_id,
            pids=pids,
            include_followers=include_followers,
        )
        if message_type != "sms" or not pids:
            return recipients_data

        sms_pids = set(pids)
        for rdata in recipients_data.values():
            for pid, pdata in rdata.items():
                if pid in sms_pids:
                    pdata["notif"] = "sms"
        return recipients_data
