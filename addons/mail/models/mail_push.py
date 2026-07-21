import logging
from datetime import timedelta

from requests import Session

from odoo import api, fields, models
from odoo.fields import Domain

from odoo.addons.mail.tools.web_push import (
    DeviceUnreachableError,
    PushEndpointUnresolvableError,
    push_to_end_point,
)

_logger = logging.getLogger(__name__)

# Keep retrying a transiently-unresolvable push endpoint for at most this many
# days; past that the resolver is treated as permanently dead and the queued
# notification is dropped so it cannot accumulate forever.
PUSH_ENDPOINT_RETRY_DAYS = 3
# How long a notification whose endpoint was unresolvable is held back before it
# is eligible again. Without a hold-off the kept rows -- which are the oldest,
# hence the lowest ids, hence the head of every `id ASC` batch -- were re-picked
# on every single run, so one dead endpoint host starved the entire queue for
# PUSH_ENDPOINT_RETRY_DAYS while the cron re-armed itself in a tight loop.
PUSH_ENDPOINT_RETRY_DELAY = timedelta(minutes=15)


class MailPush(models.Model):
    _name = "mail.push"
    _description = "Push Notifications"

    mail_push_device_id = fields.Many2one(
        "mail.push.device", string="devices", required=True, ondelete="cascade"
    )
    payload = fields.Text()
    retry_after = fields.Datetime(
        string="Retry After",
        help="Set when the device endpoint could not be resolved; the "
        "notification is skipped by the sending cron until this date so a "
        "single unreachable endpoint cannot starve the rest of the queue.",
        index=True,
    )

    @api.model
    def _get_due_domain(self):
        """Domain selecting the notifications the cron may attempt right now."""
        return Domain("retry_after", "=", False) | Domain(
            "retry_after", "<=", fields.Datetime.now()
        )

    @api.model
    def _push_notification_to_endpoint(self, batch_size=50):
        """Send to web browser endpoint computed notification"""
        due_domain = self._get_due_domain()
        web_push_notifications_sudo = self.sudo().search_fetch(
            due_domain, ["mail_push_device_id", "payload"], limit=batch_size
        )
        if not web_push_notifications_sudo:
            return

        ir_parameter_sudo = self.env["ir.config_parameter"].sudo()
        vapid_private_key = ir_parameter_sudo.get_param(
            "mail.web_push_vapid_private_key"
        )
        vapid_public_key = ir_parameter_sudo.get_param("mail.web_push_vapid_public_key")
        if not vapid_private_key or not vapid_public_key:
            return

        session = Session()
        devices_to_unlink = set()
        unresolvable_notif_ids = set()

        # process send notif
        base_url = self.get_base_url()  # constant per run; hoisted out of the loop
        devices = web_push_notifications_sudo.mail_push_device_id.grouped("id")
        for web_push_notification_sudo in web_push_notifications_sudo:
            device = devices.get(web_push_notification_sudo.mail_push_device_id.id)
            if device.id in devices_to_unlink:
                continue
            try:
                push_to_end_point(
                    base_url=base_url,
                    device={
                        "id": device.id,
                        "endpoint": device.endpoint,
                        "keys": device.keys,
                    },
                    payload=web_push_notification_sudo.payload,
                    vapid_private_key=vapid_private_key,
                    vapid_public_key=vapid_public_key,
                    session=session,
                )
            except DeviceUnreachableError:
                devices_to_unlink.add(device.id)
            except PushEndpointUnresolvableError:
                # transient (DNS blip / proxy-only egress): keep the device and
                # the queued notification and retry on the next cron run rather
                # than deleting them
                unresolvable_notif_ids.add(web_push_notification_sudo.id)
                _logger.info(
                    "Push endpoint temporarily unresolvable, keeping device %s",
                    device.id,
                )
            except Exception as e:
                # Avoid blocking the whole cron just for a notification exception
                _logger.error("An error occurred while trying to send web push: %s", e)

        # clean up notif: drop everything we attempted, except notifications
        # whose endpoint hit a transient PushEndpointUnresolvableError and are
        # still within the retry window — those are left in place for the next
        # cron run (matching the log above). Ones older than the window are
        # dropped so a permanently dead resolver cannot accumulate rows.
        retry_cutoff = fields.Datetime.now() - timedelta(days=PUSH_ENDPOINT_RETRY_DAYS)
        notifs_to_keep = web_push_notifications_sudo.filtered(
            lambda n: (
                n.id in unresolvable_notif_ids
                and n.create_date
                and n.create_date > retry_cutoff
            )
        )
        (web_push_notifications_sudo - notifs_to_keep).unlink()
        # Hold the kept ones back: they are the oldest rows, so without this they
        # are the head of every subsequent `id ASC` batch and no other
        # notification ever gets sent while the endpoint stays unresolvable.
        if notifs_to_keep:
            notifs_to_keep.retry_after = (
                fields.Datetime.now() + PUSH_ENDPOINT_RETRY_DELAY
            )

        # clean up obsolete devices
        if devices_to_unlink:
            self.env["mail.push.device"].sudo().browse(devices_to_unlink).unlink()

        # restart the cron if needed -- only for work that is actually due, else
        # the rows we just held back would re-arm the cron in a tight loop.
        if self.sudo().search_count(self._get_due_domain(), limit=1) > 0:
            self.env.ref("mail.ir_cron_web_push_notification")._trigger()
