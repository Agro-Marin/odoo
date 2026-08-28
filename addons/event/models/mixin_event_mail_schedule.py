from odoo import api, fields, models


class MixinEventMailSchedule(models.AbstractModel):
    """What an event communication is scheduled as, independent of what it hangs on.

    ``event.mail`` (on an event) and ``event.type.mail`` (on a template) carried
    an identical copy of this: the same five fields, the same notification-type
    compute and the same value preparation. The copies had already drifted -- the
    two ``interval_type`` labels differed by a trailing space -- and every module
    adding a channel had to extend both models with the same two ``selection_add``
    lines. Extending this one abstract model reaches both.
    """

    _name = "mixin.event.mail.schedule"
    _description = "Event Communication Scheduling"

    interval_nbr = fields.Integer("Interval", default=1)
    interval_unit = fields.Selection(
        [
            ("now", "Immediately"),
            ("hours", "Hours"),
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
        ],
        string="Unit",
        default="hours",
        required=True,
    )
    interval_type = fields.Selection(
        [
            # attendee based
            ("after_sub", "After each registration"),
            # event based: start date
            ("before_event", "Before the event starts"),
            ("after_event_start", "After the event started"),
            # event based: end date
            ("after_event", "After the event ended"),
            ("before_event_end", "Before the event ends"),
        ],
        string="Trigger",
        default="before_event",
        required=True,
        help="Indicates when the communication is sent. "
        "If the event has multiple slots, the interval is related to each time slot instead of the whole event.",
    )
    notification_type = fields.Selection(
        [("mail", "Mail")], string="Send", compute="_compute_notification_type"
    )
    template_ref = fields.Reference(
        string="Template",
        ondelete={"mail.template": "cascade"},
        required=True,
        selection=[("mail.template", "Mail")],
    )

    @api.depends("template_ref")
    def _compute_notification_type(self):
        """Assigns the type of template in use, if any is set."""
        self.notification_type = "mail"

    def _template_model_by_notification_type(self):
        """Which template model each notification type must point at."""
        return {
            "mail": "mail.template",
        }

    def _prepare_event_mail_values(self):
        """The scheduling half of this record, as values for the other model."""
        self.ensure_one()
        return {
            "interval_nbr": self.interval_nbr,
            "interval_unit": self.interval_unit,
            "interval_type": self.interval_type,
            "template_ref": f"{self.template_ref._name},{self.template_ref.id}",
        }
