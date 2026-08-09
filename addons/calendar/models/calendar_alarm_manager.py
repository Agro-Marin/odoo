# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models
from odoo.libs.sql import SQL
from odoo.tools import plaintext2html


class CalendarAlarm_Manager(models.AbstractModel):
    _name = "calendar.alarm_manager"
    _description = "Event Alarm Manager"

    def _get_next_potential_limit_alarm(self, alarm_type, seconds=None, partners=None):
        # flush models before making queries
        for model_name in ("calendar.alarm", "calendar.event", "calendar.recurrence"):
            self.env[model_name].flush_model()

        result = {}
        # Composed with SQL() fragments that each carry their own parameters,
        # rather than %-formatting three strings together with one flat tuple:
        # there the parameter order was positional *across* fragments and a
        # str.replace spliced in the partner filter, so reordering a fragment
        # silently misbound the parameters. Its sibling _get_events_by_alarm_to_notify
        # already uses SQL() -- the fork has the right tool.
        calcul_delta = SQL(
            """
            SELECT rel.calendar_event_id,
                   max(alarm.duration_minutes) AS max_delta,
                   min(alarm.duration_minutes) AS min_delta
              FROM calendar_alarm_calendar_event_rel AS rel
              LEFT JOIN calendar_alarm AS alarm ON alarm.id = rel.calendar_alarm_id
             WHERE alarm.alarm_type = %s
             GROUP BY rel.calendar_event_id
            """,
            alarm_type,
        )

        # Optional restriction to events attended by the given partners.
        partner_join = SQL("")
        if partners:
            partner_join = SQL(
                """INNER JOIN calendar_event_res_partner_rel AS part_rel
                           ON part_rel.calendar_event_id = cal.id
                          AND part_rel.res_partner_id = ANY(%s)""",
                list(partners.ids),
            )

        all_events = SQL(
            """
            SELECT cal.id,
                   cal.start - interval '1' minute * calcul_delta.max_delta AS first_alarm,
                   cal.stop - interval '1' minute * calcul_delta.min_delta AS last_alarm,
                   cal.start AS first_meeting,
                   cal.stop AS last_meeting,
                   calcul_delta.min_delta,
                   calcul_delta.max_delta
              FROM calendar_event AS cal
              INNER JOIN calcul_delta ON calcul_delta.calendar_event_id = cal.id
              %s
             WHERE cal.active = True
            """,
            partner_join,
        )

        # Upper bound on the first_alarm of the events we return.
        if seconds is None:
            # the next future alarm + 3 minutes if there is one, otherwise now
            first_alarm_max_value = SQL(
                """COALESCE(
                    (SELECT MIN(cal.start - interval '1' minute * calcul_delta.max_delta)
                       FROM calendar_event cal
                       RIGHT JOIN calcul_delta ON calcul_delta.calendar_event_id = cal.id
                      WHERE cal.start - interval '1' minute * calcul_delta.max_delta > now() at time zone 'utc'
                    ) + interval '3' minute,
                    now() at time zone 'utc'
                )"""
            )
        else:
            # now + the given number of seconds
            first_alarm_max_value = SQL(
                "now() at time zone 'utc' + %s * interval '1' second", seconds
            )

        self.env.flush_all()
        self.env.cr.execute(
            SQL(
                """
                WITH calcul_delta AS (%s)
                SELECT *
                  FROM (%s) AS all_events
                 WHERE all_events.first_alarm < %s
                   AND all_events.last_alarm > (now() at time zone 'utc')
                """,
                calcul_delta,
                all_events,
                first_alarm_max_value,
            )
        )

        for (
            event_id,
            first_alarm,
            last_alarm,
            first_meeting,
            last_meeting,
            min_duration,
            max_duration,
        ) in self.env.cr.fetchall():
            result[event_id] = {
                "event_id": event_id,
                "first_alarm": first_alarm,
                "last_alarm": last_alarm,
                "first_meeting": first_meeting,
                "last_meeting": last_meeting,
                "min_duration": min_duration,
                "max_duration": max_duration,
            }

        # determine accessible events
        events = self.env["calendar.event"].browse(result)
        result = {key: result[key] for key in events._filtered_access("read").ids}
        return result

    def do_check_alarm_for_one_date(
        self,
        one_date,
        event,
        in_the_next_X_seconds,
        alarm_type,
        after=False,
    ):
        """Alarms of `event` that fire within the next `in_the_next_X_seconds`.

        :param one_date: start of the occurrence to check (not the event's own
            start when it is recurrent)
        :param event: <calendar.event> record
        :param in_the_next_X_seconds: how far into the future to look
        :param after: only return alarms firing strictly after this datetime --
            the user's last acknowledgement
        :return: list of {alarm_id, event_id, notify_at}
        """
        # `event_maxdelta` and `missing` used to be parameters here. No caller
        # ever passed `missing`, so `missing * duration` was always zero and
        # `event_maxdelta` only fed a bound that the loop overwrote on its first
        # iteration -- the code said as much ("TODO: remove event_maxdelta").
        result = []
        future = fields.Datetime.now() + timedelta(seconds=in_the_next_X_seconds)
        acknowledged_until = fields.Datetime.from_string(after) if after else None
        for alarm in event.alarm_ids:
            if alarm.alarm_type != alarm_type:
                continue
            notify_at = one_date - timedelta(minutes=alarm.duration_minutes)
            if future <= notify_at:
                continue
            # Compare the acknowledgement against the moment the reminder fires,
            # not against the event's start. Comparing against the start meant an
            # acknowledgement only counted once the event had already begun: the
            # web client hides a dismissed reminder for the rest of the session,
            # but every reload asked the server again and got it back.
            if acknowledged_until is not None and notify_at <= acknowledged_until:
                continue
            result.append(
                {
                    "alarm_id": alarm.id,
                    "event_id": event.id,
                    "notify_at": notify_at,
                }
            )
        return result

    @api.model
    def _get_notify_alert_extra_conditions(self):
        """
        To be overriden on inherited modules
        adding extra conditions to extract only the unsynced events
        """
        return SQL("")

    def _get_events_by_alarm_to_notify(self, alarm_type):
        """
        Get the events with an alarm of the given type between the cron
        last call and now.

        Please note that all new reminders created since the cron last
        call with an alarm prior to the cron last call are skipped by
        design. The attendees receive an invitation for any new event
        already.
        """
        extra_conditions = self._get_notify_alert_extra_conditions()
        now = fields.Datetime.now()
        # Window is [lastcall, now). The one-week fallback (when the cron has no
        # recorded previous run) is a deliberate catch-up: it lets a run that is
        # several days late still pick up missed reminders and, for recurrences,
        # schedule the next occurrence's trigger. Keep the week, but express the
        # bound as a datetime rather than fields.Date.today(), which is a date and
        # gets widened to midnight when compared against the `start` timestamp.
        lastcall = self.env.context.get("lastcall") or (now - timedelta(weeks=1))
        self.env.cr.execute(
            SQL(
                """
            SELECT alarm.id, event.id
              FROM calendar_event AS event
              JOIN calendar_alarm_calendar_event_rel AS event_alarm_rel
                ON event.id = event_alarm_rel.calendar_event_id
              JOIN calendar_alarm AS alarm
                ON event_alarm_rel.calendar_alarm_id = alarm.id
             WHERE alarm.alarm_type = %s
               AND event.active
               AND event.start - CAST(alarm.duration || ' ' || alarm.interval AS Interval) >= %s
               AND event.start - CAST(alarm.duration || ' ' || alarm.interval AS Interval) < %s
               %s
        """,
                alarm_type,
                lastcall,
                now,
                extra_conditions,
            )
        )

        events_by_alarm = {}
        for alarm_id, event_id in self.env.cr.fetchall():
            events_by_alarm.setdefault(alarm_id, []).append(event_id)
        return events_by_alarm

    @api.model
    def _send_reminder(self):
        # Executed via cron
        events_by_alarm = self._get_events_by_alarm_to_notify("email")
        if not events_by_alarm:
            return

        # force_send limit should apply to the total nb of attendees, not per alarm
        force_send_limit = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("mail.mail_force_send_limit", 100)
        )

        event_ids = list(
            {
                event_id
                for event_ids in events_by_alarm.values()
                for event_id in event_ids
            }
        )
        events = self.env["calendar.event"].browse(event_ids)
        now = fields.Datetime.now()
        attendees = events.filtered(lambda e: e.stop > now).attendee_ids.filtered(
            lambda a: a.state != "declined"
        )
        alarms = self.env["calendar.alarm"].browse(events_by_alarm.keys())
        for alarm in alarms:
            alarm_attendees = attendees.filtered(
                lambda attendee, alarm=alarm: attendee.event_id.id in events_by_alarm[alarm.id]
            )
            alarm_attendees.with_context(
                calendar_template_ignore_recurrence=True
            )._notify_attendees(
                alarm.mail_template_id,
                force_send=len(attendees) <= force_send_limit,
                notify_author=True,
            )

        events._setup_event_recurrent_alarms(events_by_alarm)

    @api.model
    def get_next_notif(self):
        partner = self.env.user.partner_id
        if not partner:
            return []

        all_meetings = self._get_next_potential_limit_alarm(
            "notification", partners=partner
        )
        # One browse for the whole set, not one per notification: this route is
        # polled by every open tab, and `display_time` below is a compute, so a
        # per-event browse made the query count scale with the user's alarms
        # (measured ~5 queries per pending notification).
        meetings = self.env["calendar.event"].browse(all_meetings)
        time_limit = 3600 * 24  # return alarms of the next 24 hours
        all_notif = []
        for meeting in meetings:
            alerts = self.do_check_alarm_for_one_date(
                meeting.start,
                meeting,
                time_limit,
                "notification",
                after=partner.calendar_last_notif_ack,
            )
            all_notif.extend(self.do_notif_reminder(alert) for alert in alerts)
        return all_notif

    def do_notif_reminder(self, alert):
        alarm = self.env["calendar.alarm"].browse(alert["alarm_id"])
        meeting = self.env["calendar.event"].browse(alert["event_id"])

        if alarm.alarm_type == "notification":
            # Markup, and one paragraph: `plaintext2html` already wraps its
            # result in <p>, so wrapping it again emitted `<p><p>body</p></p>`,
            # and building the whole thing as a plain str meant the web client
            # -- which renders it with `t-out` -- escaped the tags and showed
            # them to the user verbatim. The client marks this value up on
            # arrival (see calendar_notification_service.js).
            message = Markup("%s") % meeting.display_time
            if alarm.body:
                message += plaintext2html(alarm.body)

            delta = alert["notify_at"] - fields.Datetime.now()
            delta = delta.seconds + delta.days * 3600 * 24

            return {
                "alarm_id": alarm.id,
                "event_id": meeting.id,
                "title": meeting.name,
                "message": message,
                "timer": delta,
                "notify_at": fields.Datetime.to_string(alert["notify_at"]),
            }
        return None

    def _notify_next_alarm(self, partner_ids):
        """Sends through the bus the next alarm of given partners"""
        users = self.env["res.users"].search(
            [
                ("partner_id", "in", tuple(partner_ids)),
                ("group_ids", "in", self.env.ref("base.group_user").ids),
            ]
        )
        for user in users:
            notif = (
                self.with_user(user)
                .with_context(allowed_company_ids=user.company_ids.ids)
                .get_next_notif()
            )
            user._bus_send("calendar.alarm", notif)
