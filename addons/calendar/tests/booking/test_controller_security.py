from datetime import datetime, timedelta
from itertools import product
from urllib.parse import urlencode as url_encode

from freezegun import freeze_time

from odoo import http
from odoo.tests import tagged

from .test_appointment_ui import AppointmentUICommon


@tagged("appointment_ui", "security", "-at_install", "post_install")
class AppointmentControllerSecurity(AppointmentUICommon):
    def test_conference_token_cannot_manage_ordinary_meeting(self):
        start = datetime.now() + timedelta(days=7)
        event = self.env["calendar.event"].create(
            {
                "name": "Private ordinary meeting",
                "privacy": "private",
                "start": start,
                "stop": start + timedelta(hours=1),
                "partner_ids": [(6, 0, self.staff_user_bxls.partner_id.ids)],
            }
        )
        event._set_discuss_videocall_location()
        token = event.access_token
        self.assertTrue(token)
        self.authenticate(None, None)
        for path in (
            f"/calendar/view/{token}",
            f"/calendar/ics/{token}.ics",
            f"/calendar/cancel/{token}",
            f"/calendar/{token}/cancel",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    self.url_open(path, allow_redirects=False).status_code,
                    405 if "/cancel" in path else 404,
                )
        event.invalidate_recordset(["active"])
        self.assertTrue(event.active)
        guest_response = self.url_open(
            f"/calendar/{token}/add_attendees_from_emails",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "call",
                "params": {"emails_str": "unauthorized-guest@example.test"},
            },
        )
        self.assertIn("error", guest_response.json())
        event.invalidate_recordset(["partner_ids"])
        self.assertEqual(event.partner_ids, self.staff_user_bxls.partner_id)
        attendee = event.attendee_ids
        invitation = self.url_open(
            f"/calendar/meeting/view?token={attendee.access_token}&id={event.id}",
            allow_redirects=False,
        )
        self.assertEqual(invitation.status_code, 303)

    def test_appointment_token_keeps_view_download_and_cancellation(self):
        start = datetime.now() + timedelta(days=7)
        event = self.env["calendar.event"].create(
            {
                "name": "Appointment token control",
                "start": start,
                "stop": start + timedelta(hours=1),
                "appointment_type_id": self.apt_type_bxls_2days.id,
                "user_id": self.staff_user_bxls.id,
                "partner_ids": [(6, 0, self.staff_user_bxls.partner_id.ids)],
            }
        )
        event._update_access_token()
        self.authenticate(None, None)
        token = event.booking_access_token
        self.assertEqual(self.url_open(f"/calendar/view/{token}").status_code, 200)
        self.assertEqual(self.url_open(f"/calendar/ics/{token}.ics").status_code, 200)
        self.assertEqual(
            self.url_open(
                f"/calendar/cancel/{token}",
                data={"csrf_token": http.Request.csrf_token(self)},
                allow_redirects=False,
            ).status_code,
            303,
        )
        event.invalidate_recordset(["active"])
        self.assertFalse(event.active)

    @freeze_time("2022-07-04")
    def test_appointment_submit_no_csrf(self):
        """Check that the form does not require a CSRF token when logged out.

        When logged out we should always create a new partner regardless of whether one exists
        with similar contact info, so it is ok to not check CSRF as we do not use any session-related
        information during form submission.
        """
        invite = self.env["appointment.invite"].create(
            {
                "appointment_type_ids": self.apt_type_bxls_2days.ids,
                "resources_choice": "all_assigned_resources",
            }
        )
        appointment_url = f"/appointment/{self.apt_type_bxls_2days.id}/submit?{url_encode(invite._get_redirect_url_parameters())}"
        phone_question = self.apt_type_bxls_2days._get_main_phone_question()
        self.assertTrue(phone_question)

        base_appointment_data = {
            "allday": 0,
            "csrf_token": False,
            "duration_str": "1.0",
            "datetime_str": "2022-07-04 10:00:00",
            "email": self.apt_manager.email,
            "name": "logged-out Apt Manager",
            f"question_{phone_question.id}": self.apt_manager._phone_get_number().number,
            "staff_user_id": self.staff_user_bxls.id,
        }
        existing_partners = (
            self.staff_user_bxls.partner_id + self.apt_manager.partner_id
        )
        for offset, (login, with_csrf) in enumerate(
            product((None, self.apt_manager.login), (False, True))
        ):
            with self.subTest(login=login, with_csrf=with_csrf):
                self.authenticate(login, login)
                # Book a different slot on each iteration: the submit route now
                # refuses an already-taken slot, and this type allows one booking
                # per slot.
                slot_data = base_appointment_data | {
                    "datetime_str": f"2022-07-04 {10 + offset}:00:00",
                }
                res = self.url_open(
                    appointment_url,
                    data=slot_data
                    | (
                        {"csrf_token": http.Request.csrf_token(self)}
                        if with_csrf
                        else {}
                    ),
                )

                if not login or with_csrf:
                    self.assertTrue(res.ok)
                    self.assertIn("/calendar/view/", res.url)
                else:
                    self.assertFalse(res.ok)
                    continue

                latest_partner = self.env["res.partner"].search(
                    [], order="id DESC", limit=1
                )
                latest_appointment = self.env["calendar.event"].search(
                    [], order="id DESC", limit=1
                )

                if not login:
                    self.assertNotIn(latest_partner, existing_partners)

                    self.assertEqual(latest_partner.email, self.apt_manager.email)
                    self.assertEqual(latest_partner.name, "logged-out Apt Manager")
                    self.assertEqual(
                        latest_appointment.partner_ids,
                        latest_partner + self.staff_user_bxls.partner_id,
                    )
                    self.assertNotEqual(latest_partner, self.apt_manager.partner_id)
                elif login and with_csrf:
                    self.assertEqual(
                        latest_appointment.partner_ids,
                        self.apt_manager.partner_id + self.staff_user_bxls.partner_id,
                    )
                existing_partners |= latest_partner
                # avoid using up a slot for following tests
                latest_appointment.unlink()
