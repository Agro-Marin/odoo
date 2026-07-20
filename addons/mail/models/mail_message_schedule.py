import json
import logging
from datetime import UTC, datetime

from odoo import api, fields, models, modules
from odoo.service.transaction import PG_CONCURRENCY_ERRORS_TO_RETRY

_logger = logging.getLogger(__name__)


class MailMessageSchedule(models.Model):
    """Queue to delay a message's notifications. Unlike mail.mail's
    scheduled_date, this also delays the <bus.bus> notifications.
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
        batch_size = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("mail.scheduled_notification.batch.size", 500)
        )
        # limit + 1: detect whether a follow-up run is needed without a count()
        messages_scheduled = self.env["mail.message.schedule"].search(
            [("scheduled_datetime", "<=", datetime.now(UTC))],
            limit=batch_size + 1,
        )
        has_more = len(messages_scheduled) > batch_size
        messages_scheduled = messages_scheduled[:batch_size]
        if not messages_scheduled:
            return
        _logger.info("Send %s scheduled messages", len(messages_scheduled))
        # Isolate each schedule: without this, a single failing _notify_thread
        # (broken template, recipient with a bad lang/company, uninstalled
        # model, …) would roll back the whole batch and be retried unchanged on
        # every cron tick, indefinitely blocking every other user's scheduled
        # notifications (poison pill). Commit per schedule and drop failed rows,
        # mirroring mail.scheduled.message._post_message. skip_existing=True
        # already guards against re-notifying on replay.
        auto_commit = not modules.module.current_test
        for schedule in messages_scheduled:
            try:
                schedule._send_notifications()
                if auto_commit:
                    self.env.cr.commit()
            except Exception as error:
                if auto_commit:
                    self.env.cr.rollback()
                # Distinguish a *transient* DB error (serialization failure,
                # deadlock, lock timeout -- realistic in this concurrent-session
                # workspace) from a deterministic poison pill (broken template,
                # recipient with a bad lang, uninstalled model). Dropping the row
                # on a transient error would silently lose a real message's whole
                # notification fan-out; leave it in place to retry on the next
                # tick. Only deterministic failures are dropped, so a single bad
                # row can still never wedge the queue forever.
                if getattr(error, "sqlstate", None) in PG_CONCURRENCY_ERRORS_TO_RETRY:
                    _logger.warning(
                        "Transient DB error sending scheduled notification %s; "
                        "leaving it to retry on the next tick",
                        schedule.id,
                        exc_info=True,
                    )
                    continue
                _logger.warning(
                    "Sending of scheduled notification %s failed; dropping it",
                    schedule.id,
                    exc_info=True,
                )
                try:
                    schedule.unlink()
                except Exception:
                    _logger.exception(
                        "Could not drop the failed scheduled notification %s",
                        schedule.id,
                    )
                    if auto_commit:
                        self.env.cr.rollback()
                if auto_commit:
                    self.env.cr.commit()
        # More than one batch was due: re-trigger so the queue drains promptly
        # instead of waiting for the cron's next natural tick.
        if has_more:
            self.env.ref("mail.ir_cron_send_scheduled_message")._trigger()

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
                except Exception:
                    # Fall back to default notify kwargs, but leave a trace: a
                    # silently-dropped payload means the notification goes out
                    # with wrong company branding / auto-delete and nothing to
                    # explain it.
                    _logger.warning(
                        "Invalid notification_parameters on mail.message.schedule %s; "
                        "using defaults.",
                        schedule.id,
                        exc_info=True,
                    )
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
