from collections import defaultdict

from odoo import _, api, fields, models
from odoo.tools import SQL


class ResPartner(models.Model):
    _inherit = 'res.partner'

    meeting_count = fields.Integer("# Meetings", compute='_compute_meeting_count')
    meeting_ids = fields.Many2many('calendar.event', 'calendar_event_res_partner_rel', 'res_partner_id',
                                   'calendar_event_id', string='Meetings', copy=False)

    calendar_last_notif_ack = fields.Datetime(
        'Last notification marked as read from base Calendar', default=fields.Datetime.now)

    def _compute_meeting_count(self):
        result = self._compute_meeting()
        for p in self:
            p.meeting_count = len(result.get(p.id, []))

    def _compute_meeting(self):
        if self.ids:
            # prefetch 'parent_id'
            all_partners = self.with_context(active_test=False).search_fetch(
                [('id', 'child_of', self.ids)], ['parent_id'],
            )

            query = self.env['calendar.event']._search([])  # ir.rules will be applied
            meeting_data = self.env.execute_query(SQL("""
                SELECT DISTINCT res_partner_id, calendar_event_id
                  FROM calendar_event_res_partner_rel
                 WHERE res_partner_id = ANY(%s) AND calendar_event_id IN %s
                """,
                list(all_partners._ids),
                query.subselect(),
            ))

            # Create a dict {partner_id: event_ids} and fill with events linked to the partner
            meetings = {}
            for p_id, m_id in meeting_data:
                meetings.setdefault(p_id, set()).add(m_id)

            # Roll each partner's meetings up to whichever of its ancestors are
            # in `self`. `in self` is a scan of the recordset, and it sat inside
            # a walk up the parent chain of every partner that had a meeting, so
            # the cost was O(partners x depth x len(self)); the ids are known up
            # front.
            wanted_ids = set(self._ids)
            for p in self.browse(meetings.keys()):
                partner = p
                while partner.parent_id:
                    partner = partner.parent_id
                    if partner.id in wanted_ids:
                        meetings[partner.id] = meetings.get(partner.id, set()) | meetings[p.id]
            return {p_id: list(meetings.get(p_id, set())) for p_id in self.ids}
        return {}

    def _get_application_statistics(self):
        data_list = super()._get_application_statistics()
        for partner in self.filtered('meeting_count'):
            stat_info = {'iconClass': 'fa-solid fa-calendar', 'value': partner.meeting_count, 'label': _('Meetings'), 'tagClass': 'o_tag_color_3'}
            data_list[partner.id].append(stat_info)
        return data_list

    def get_attendee_detail(self, meeting_ids):
        """ Return a list of dict of the given meetings with the attendees details
            Used by:

            - many2many_attendee.js: Many2ManyAttendee
            - calendar_model.js (calendar.CalendarModel)
        """
        attendees_details = []
        meetings = self.env['calendar.event'].browse(meeting_ids)
        for attendee in meetings.attendee_ids:
            if attendee.partner_id not in self:
                continue
            attendee_is_organizer = self.env.user == attendee.event_id.user_id and attendee.partner_id == self.env.user.partner_id
            attendees_details.append({
                'id': attendee.partner_id.id,
                'name': attendee.partner_id.display_name,
                'status': attendee.state,
                'event_id': attendee.event_id.id,
                'attendee_id': attendee.id,
                'is_alone': attendee.event_id.is_organizer_alone and attendee_is_organizer,
                # attendees data is sorted according to this key in JS.
                'is_organizer': 1 if attendee.partner_id == attendee.event_id.user_id.partner_id else 0,
            })
        return attendees_details

    @api.model
    def _set_calendar_last_notif_ack(self):
        """Stamp the calling user's reminder acknowledgement."""
        # `self.env.user`, not `self.env.context.get('uid', ...)`: the route calls
        # this through sudo(), and taking the identity from a context key means
        # any caller able to set `uid` in the context stamps somebody else's
        # partner. `fields.Datetime.now()` rather than `datetime.now()` for the
        # same reason every other write of this column uses it -- the two agree
        # today, and the field's own default is already spelled this way.
        self.env.user.partner_id.write({
            'calendar_last_notif_ack': fields.Datetime.now(),
        })

    def schedule_meeting(self):
        self.check_singleton()
        action = self.env["ir.actions.actions"]._get_action_dict_by_xml_id("calendar.action_calendar_event")
        # Not `partner_ids = self.ids; partner_ids.append(...)`: that reads as a
        # mutation of the recordset's own ids and is only safe because `ids`
        # happens to build a fresh list each time.
        action['context'] = {
            'default_partner_ids': [*self.ids, self.env.user.partner_id.id],
        }
        # The first branch carries the meetings of this partner's *children*,
        # which the second cannot express as a domain.
        action['domain'] = ['|', ('id', 'in', self._compute_meeting()[self.id]), ('partner_ids', 'in', self.ids)]
        return action

    def _get_busy_calendar_events(self, start_datetime, end_datetime):
        """Get a mapping from partner id to attended events intersecting with the time interval.

        :rtype: dict[int, <calendar.event>]
        """
        return self._group_busy_calendar_events(
            self._search_busy_calendar_events(start_datetime, end_datetime),
            start_datetime,
            end_datetime,
        )

    def _search_busy_calendar_events(self, start_datetime, end_datetime):
        """Events attended by `self`, shown as busy, intersecting the interval.

        Split out of `_get_busy_calendar_events` so a caller holding several
        intervals can pay for one search over their whole span and slice it per
        interval with `_group_busy_calendar_events`, instead of one search per
        interval (see `calendar.event._compute_unavailable_partner_ids`).

        :rtype: <calendar.event>
        """
        return self.env['calendar.event'].search([
            ('stop', '>=', start_datetime.replace(tzinfo=None)),
            ('start', '<=', end_datetime.replace(tzinfo=None)),
            ('partner_ids', 'in', self.ids),
            ('show_as', '=', 'busy'),
        ])

    def _group_busy_calendar_events(self, events, start_datetime, end_datetime):
        """Bucket the part of `events` intersecting the interval, by attendee.

        Keyed by every partner attending a kept event, not only by the partners
        of `self` -- which is what `_get_busy_calendar_events` has always
        returned, and restricting it here would silently change that method for
        its callers outside this module. Callers read the keys they asked about;
        the extra ones are inert.

        The bounds are the closed ones `_search_busy_calendar_events` compares
        against: an event that merely touches an edge counts as busy there, so
        the search and the slice must not disagree about it.

        :rtype: dict[int, <calendar.event>]
        """
        start = start_datetime.replace(tzinfo=None)
        stop = end_datetime.replace(tzinfo=None)
        event_by_partner_id = defaultdict(lambda: self.env['calendar.event'])
        for event in events:
            if not (event.stop >= start and event.start <= stop):
                continue
            for partner in event.partner_ids:
                event_by_partner_id[partner.id] |= event
        return dict(event_by_partner_id)
