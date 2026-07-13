import json
import logging
from datetime import UTC, datetime

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class MailMessageSchedule(models.Model):
    """Mail message notification schedule queue.

    This model is used to store the mail messages scheduled. So we can
    delay the sending of the notifications. A scheduled date field already
    exists on the <mail.mail> but it does not allow us to delay the sending
    of the <bus.bus> notifications.
    """

    _name = "mail.message.schedule"
    _description = "Scheduled Messages"
    _order = "scheduled_datetime DESC, id DESC"
    _rec_name = "mail_message_id"

    mail_message_id = fields.Many2one(
        "mail.message", string="Message", ondelete="cascade", required=True
    )
    notification_parameters = fields.Text("Notification Parameter")
    scheduled_datetime = fields.Datetime(
        "Scheduled Send Date",
        required=True,
        help="Datetime at which notification should be sent.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        schedules = super().create(vals_list)
        if schedules:
            self.env.ref("mail.ir_cron_send_scheduled_message")._trigger_list(
                set(schedules.mapped("scheduled_datetime"))
            )
        return schedules

    @api.model
    def _send_notifications_cron(self):
        messages_scheduled = self.env["mail.message.schedule"].search(
            [("scheduled_datetime", "<=", datetime.now(UTC))]
        )
        if messages_scheduled:
            _logger.info("Send %s scheduled messages", len(messages_scheduled))
            messages_scheduled._send_notifications()

    def force_send(self):
        """Launch notification process independently from the expected date."""
        return self._send_notifications()

    def _send_notifications(self, default_notify_kwargs=None):
        """Send notification for scheduled messages.

        :param dict default_notify_kwargs: optional parameters to propagate to
          ``notify_thread``. Those are default values overridden by content of
          ``notification_parameters`` field.
        """
        for model, schedules in self._group_by_model().items():
            # Resolve the record per schedule: two schedules may share a
            # mail_message_id, so ``schedules.mapped("mail_message_id.res_id")``
            # deduplicates and the positional ``zip`` would drop (and then
            # unlink unsent) the tail schedules. Pre-compute the existing ids
            # from a single browse for prefetching.
            existing_ids = ()
            if model:
                res_ids = schedules.mapped("mail_message_id.res_id")
                existing_ids = set(self.env[model].browse(res_ids).exists()._ids)

            for schedule in schedules:
                if model:
                    record = self.env[model].browse(schedule.mail_message_id.res_id)
                    if record.id not in existing_ids:
                        continue
                else:
                    record = self.env["mail.thread"]
                notify_kwargs = dict(default_notify_kwargs or {}, skip_existing=True)
                try:
                    schedule_notify_kwargs = (
                        schedule._deserialize_notification_parameters()
                    )
                except Exception:  # noqa: S110
                    pass
                else:
                    schedule_notify_kwargs.pop("scheduled_date", None)
                    notify_kwargs.update(schedule_notify_kwargs)

                record._notify_thread(
                    schedule.mail_message_id, msg_vals=False, **notify_kwargs
                )

        self.unlink()
        return True

    @api.model
    def _serialize_notification_parameters(self, notify_kwargs):
        """JSON-encode notify kwargs for the ``notification_parameters`` field.

        Some valid notify parameters are recordsets (e.g. ``force_email_company``,
        a ``res.company``) that ``json.dumps`` cannot serialize; store them as ids
        so they survive the round-trip through the queue and can be rebuilt on
        replay by ``_deserialize_notification_parameters``.
        """
        serializable = dict(notify_kwargs)
        company = serializable.get("force_email_company")
        if company is not None and not isinstance(company, (bool, int)):
            serializable["force_email_company"] = company.id
        return json.dumps(serializable)

    def _deserialize_notification_parameters(self):
        """Decode ``notification_parameters``, rebuilding recordset-valued kwargs."""
        self.ensure_one()
        params = json.loads(self.notification_parameters or "{}")
        company_id = params.get("force_email_company")
        if company_id:
            params["force_email_company"] = self.env["res.company"].browse(company_id)
        return params

    @api.model
    def _send_message_notifications(self, messages, default_notify_kwargs=None):
        """Send scheduled notification for given messages.

        :param <mail.message> messages: scheduled sending related to those messages
          will be sent now;
        :param dict default_notify_kwargs: optional parameters to propagate to
          ``notify_thread``. Those are default values overridden by content of
          ``notification_parameters`` field.

        :returns: False if no schedule has been found, True otherwise
        :rtype: bool
        """
        messages_scheduled = self.search([("mail_message_id", "in", messages.ids)])
        if not messages_scheduled:
            return False

        messages_scheduled._send_notifications(
            default_notify_kwargs=default_notify_kwargs
        )
        return True

    @api.model
    def _update_message_scheduled_datetime(self, messages, new_datetime):
        """Update scheduled datetime for scheduled sending related to messages.

        :param <mail.message> messages: scheduled sending related to those messages
          will be updated. Missing one are skipped;
        :param datetime new_datetime: new datetime for sending. New triggers
          are created based on it;

        :returns: False if no schedule has been found, True otherwise
        :rtype: bool
        """
        messages_scheduled = self.search([("mail_message_id", "in", messages.ids)])
        if not messages_scheduled:
            return False

        messages_scheduled.scheduled_datetime = new_datetime
        self.env.ref("mail.ir_cron_send_scheduled_message")._trigger(new_datetime)
        return True

    def _group_by_model(self):
        grouped = {}
        for schedule in self:
            model = (
                schedule.mail_message_id.model
                if schedule.mail_message_id.model and schedule.mail_message_id.res_id
                else False
            )
            if model not in grouped:
                grouped[model] = schedule
            else:
                grouped[model] += schedule
        return grouped
