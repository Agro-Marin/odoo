# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import http
from odoo.http import request
from odoo.tools.misc import get_lang


class CalendarController(http.Controller):

    # ------------------------------------------------------------
    # TOKEN LOOKUP
    # ------------------------------------------------------------
    #
    # Every route below identifies its record by an invitation token taken
    # straight from the query string. `('access_token', '=', token)` with an
    # empty token matches every row whose column is NULL, so an unguarded lookup
    # turns "no token" into "any tokenless record": on `calendar.attendee` that
    # authenticated an anonymous visitor and let them answer the invitation, and
    # on `calendar.event` -- where a NULL token is the norm, every event without
    # a videocall link has one -- it matched them all at once and crashed
    # `action_join_meeting`'s `ensure_one()`. Both lookups go through these two
    # helpers so the rule is stated once.

    @staticmethod
    def _attendee_from_token(token, extra_domain=None):
        """Attendee bearing `token`, or an empty recordset for a falsy token."""
        if not token:
            return request.env['calendar.attendee']
        domain = [('access_token', '=', token), *(extra_domain or [])]
        return request.env['calendar.attendee'].sudo().search(domain, limit=1)

    @staticmethod
    def _event_from_token(token):
        """Event bearing `token`, or an empty recordset for a falsy token."""
        if not token:
            return request.env['calendar.event']
        return request.env['calendar.event'].sudo().search(
            [('access_token', '=', token)], limit=1)

    # ------------------------------------------------------------
    # ROUTES
    # ------------------------------------------------------------

    # YTI Note: Keep id and kwargs only for retrocompatibility purpose
    @http.route('/calendar/meeting/accept', type='http', auth="calendar")
    def accept_meeting(self, token, id, **kwargs):
        attendee = self._attendee_from_token(token, [('state', '!=', 'accepted')])
        attendee.do_accept()
        return self.view_meeting(token, id)

    @http.route('/calendar/recurrence/accept', type='http', auth="calendar")
    def accept_recurrence(self, token, id, **kwargs):
        attendee = self._attendee_from_token(token, [('state', '!=', 'accepted')])
        if attendee:
            attendees = request.env['calendar.attendee'].sudo().search([
                ('event_id', 'in', attendee.event_id.recurrence_id.calendar_event_ids.ids),
                ('partner_id', '=', attendee.partner_id.id),
                ('state', '!=', 'accepted'),
            ])
            attendees.do_accept()
        return self.view_meeting(token, id)

    @http.route('/calendar/meeting/decline', type='http', auth="calendar")
    def decline_meeting(self, token, id, **kwargs):
        attendee = self._attendee_from_token(token, [('state', '!=', 'declined')])
        attendee.do_decline()
        return self.view_meeting(token, id)

    @http.route('/calendar/recurrence/decline', type='http', auth="calendar")
    def decline_recurrence(self, token, id, **kwargs):
        attendee = self._attendee_from_token(token, [('state', '!=', 'declined')])
        if attendee:
            attendees = request.env['calendar.attendee'].sudo().search([
                ('event_id', 'in', attendee.event_id.recurrence_id.calendar_event_ids.ids),
                ('partner_id', '=', attendee.partner_id.id),
                ('state', '!=', 'declined'),
            ])
            attendees.do_decline()
        return self.view_meeting(token, id)

    @http.route('/calendar/meeting/view', type='http', auth="calendar")
    def view_meeting(self, token, id, **kwargs):
        attendee = self._attendee_from_token(token, [('event_id', '=', int(id))])
        if not attendee:
            return request.not_found()
        timezone = attendee.partner_id.tz
        lang = attendee.partner_id.lang or get_lang(request.env).code
        event = request.env['calendar.event'].with_context(tz=timezone, lang=lang).sudo().browse(int(id))
        company = (event.user_id and event.user_id.company_id) or event.create_uid.company_id

        # If user is internal and logged, redirect to form view of event
        # otherwise, display the simplifyed web page with event informations
        if request.env.user._is_internal():
            return request.redirect('/odoo/calendar.event/%s?db=%s' % (id, request.env.cr.dbname))

        # NOTE : we don't use request.render() since:
        # - we need a template rendering which is not lazy, to render before cursor closing
        # - we need to display the template in the language of the user (not possible with
        #   request.render())
        response_content = request.env['ir.ui.view'].with_context(lang=lang)._render_template(
            'calendar.invitation_page_anonymous', {
                'company': company,
                'event': event,
                'attendee': attendee,
            })
        return request.make_response(response_content, headers=[('Content-Type', 'text/html')])

    @http.route('/calendar/meeting/join', type='http', auth="user", website=True)
    def calendar_join_meeting(self, token, **kwargs):
        event = self._event_from_token(token)
        if not event:
            return request.not_found()
        event.action_join_meeting(request.env.user.partner_id.id)
        attendee = request.env['calendar.attendee'].sudo().search(
            [('partner_id', '=', request.env.user.partner_id.id), ('event_id', '=', event.id)],
            limit=1)
        return request.redirect('/calendar/meeting/view?token=%s&id=%s' % (attendee.access_token, event.id))

    # RPC polled by the web client to fetch the event reminders currently due; the
    # client reschedules its next call for when the last returned notification fires.
    @http.route('/calendar/notify', type='jsonrpc', auth="user")
    def notify(self):
        return request.env['calendar.alarm_manager'].get_next_notif()

    @http.route('/calendar/notify_ack', type='jsonrpc', auth="user")
    def notify_ack(self):
        # sudo: a portal user has no write access to res.partner, and the method
        # only ever stamps the caller's own partner.
        return request.env['res.partner'].sudo()._set_calendar_last_notif_ack()

    @http.route('/calendar/join_videocall/<string:access_token>', type='http', auth='public')
    def calendar_join_videocall(self, access_token):
        event = self._event_from_token(access_token)
        if not event:
            return request.not_found()

        # if channel doesn't exist
        if not event.videocall_channel_id:
            event._create_videocall_channel()

        return request.redirect(event.videocall_channel_id.invitation_url)

    @http.route('/calendar/check_credentials', type='jsonrpc', auth='user')
    def check_calendar_credentials(self):
        # method should be overwritten by sync providers
        return request.env['res.users'].check_calendar_credentials()
