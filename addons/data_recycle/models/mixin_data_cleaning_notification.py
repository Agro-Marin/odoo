from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

# The values are `relativedelta` keyword arguments, which is what lets a period
# become a delta without a branch per period. The three copies of that branch
# this replaces had already drifted: `data_merge` spelled the first one
# `relativedelta(day=n)` -- day of the month, not a number of days -- so a rule
# set to notify every 5 days moved its own deadline backwards to the 5th of the
# month and came due on every single run.
NOTIFY_PERIODS = [("days", "Days"), ("weeks", "Weeks"), ("months", "Months")]


class MixinDataCleaningNotification(models.AbstractModel):
    """Tell a rule's watchers, on a period, what it is proposing.

    Carried by `data_recycle.model`, `data_cleaning.model` and
    `data_merge.model`, which had one copy each of everything below.

    A consumer supplies `_cleaning_mode_field` and the three hooks at the end.
    """

    _name = "mixin.data.cleaning.notification"
    _description = "Data Cleaning Notification"

    #: Name of the Selection on the concrete model that reads 'manual' or
    #: 'automatic'. Automatic rules act on their own and notify nobody.
    _cleaning_mode_field = None

    notify_user_ids = fields.Many2many(
        "res.users",
        string="Notify Users",
        domain=lambda self: self._domain_notify_user_ids(),
        default=lambda self: self.env.user,
        help="List of users to notify when there are new records to review",
    )
    notify_frequency = fields.Integer(string="Notify", default=1)
    notify_frequency_period = fields.Selection(
        NOTIFY_PERIODS, string="Notify Frequency Period", default="weeks"
    )
    last_notification = fields.Datetime(readonly=True)

    _check_notify_frequency = models.Constraint(
        "CHECK(notify_frequency > 0)",
        "The notification frequency should be greater than 0",
    )

    @api.model
    def _domain_notify_user_ids(self):
        # Only a system user can reach the queues these notifications link to.
        return [("all_group_ids", "in", self.env.ref("base.group_system").id)]

    def _notify_pending_records(self):
        """Notify the watchers of every manual rule in `self` that is due."""
        mode_field = self._cleaning_mode_field
        if not mode_field:
            # Without this the filter below raises `KeyError: None` from inside a
            # cron, which says nothing about what the consumer forgot to declare.
            raise NotImplementedError(
                "%s inherits mixin.data.cleaning.notification without setting "
                "_cleaning_mode_field" % self._name
            )
        for rule in self.filtered(lambda r: r[mode_field] == "manual"):
            if not rule.notify_user_ids or not rule.notify_frequency:
                continue
            delta = relativedelta(
                **{rule.notify_frequency_period: rule.notify_frequency}
            )
            if (
                rule.last_notification
                and rule.last_notification + delta >= fields.Datetime.now()
            ):
                continue
            # Stamp only on a notification that went out. Stamping first, which
            # all three copies did, spends the period on a run that sent
            # nothing and leaves the watchers to find the backlog themselves.
            if rule._send_notification():
                rule.last_notification = fields.Datetime.now()

    def _send_notification(self):
        """Send one rule's notification. False when there was nothing to say."""
        self.ensure_one()
        records_count = self._get_count_pending()
        partner_ids = self.notify_user_ids.partner_id.ids
        if not records_count or not partner_ids:
            return False
        self.env["mixin.mail.thread"].sudo().message_notify(
            body=self._get_notification_body(records_count),
            model=self._name,
            partner_ids=partner_ids,
            res_id=self.id,
            subject=self._get_notification_subject(),
        )
        return True

    # Hooks

    def _get_count_pending(self):
        """How many records this rule is currently proposing."""
        raise NotImplementedError

    def _get_notification_body(self, records_count):
        """The rendered body of the notification."""
        raise NotImplementedError

    def _get_notification_subject(self):
        """The subject line."""
        raise NotImplementedError
