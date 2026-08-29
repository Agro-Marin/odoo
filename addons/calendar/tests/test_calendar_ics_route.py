"""The public route serving a meeting's .ics file to invitees.

The invitation mail links to it, so it answers unauthenticated requests and is
guarded by the event's `access_token` alone. Two of the cases below are about
that guard rather than about the feature, and two more read the template body
this module ships rather than the one in the database -- `noupdate="1"` means
those differ on any database that is not brand new.

Kept in its own file: `test_calendar_controller.py` predates the fork's
ruff-format hook.
"""

from datetime import datetime
from pathlib import Path

from odoo.tests.common import HttpCase, tagged

_TEMPLATE_DATA = (
    Path(__file__).resolve().parent.parent / "data" / "mail_template_data.xml"
)


def _shipped_body(xml_id):
    """The `body_html` this module ships for `xml_id`, straight from the file.

    Sliced out as text rather than parsed: an XML parser would have to be the
    hardened one for untrusted input (ruff S314), and nothing here is untrusted
    -- it is this module's own data file, sitting next to this test.
    """
    src = _TEMPLATE_DATA.read_text(encoding="utf-8")
    record = src.index(f'<record id="{xml_id}"')
    opening = src.index('<field name="body_html"', record)
    body = src.index(">", opening) + 1
    return src[body : src.index("</field>", body)]


@tagged("post_install", "-at_install")
class TestCalendarIcsRoute(HttpCase):
    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create(
            {"name": "Invitee", "email": "invitee@test.lan"}
        )
        self.event = self.env["calendar.event"].create(
            {
                "name": "Quarterly review",
                "start": datetime(2026, 4, 1, 8, 0),
                "stop": datetime(2026, 4, 1, 9, 0),
                "partner_ids": [(4, self.partner.id)],
            }
        )

    def test_a_valid_token_serves_the_ics_file(self):
        token = self.event._calendar_event_ensure_token()
        response = self.url_open(f"/calendar/ics/{self.event.id}/{token}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.content.startswith(b"BEGIN:VCALENDAR"),
            f"expected an iCalendar body, got {response.content[:40]!r}",
        )

    def test_a_wrong_token_is_not_found(self):
        self.event._calendar_event_ensure_token()
        response = self.url_open(f"/calendar/ics/{self.event.id}/not-the-token")
        self.assertEqual(response.status_code, 404)

    def test_an_event_without_a_token_is_not_found(self):
        """The case upstream's version cannot survive.

        Upstream mints a token by field default, so `access_token` is never
        NULL there and comparing it is safe. Here NULL is the norm -- only
        events with a discuss videocall have ever been given one -- and handing
        a NULL to `consteq` raises, turning a guessed URL into a 500.
        """
        self.event.access_token = False
        response = self.url_open(f"/calendar/ics/{self.event.id}/anything")
        self.assertEqual(
            response.status_code,
            404,
            "a tokenless event must be not-found, not a server error",
        )

    def test_the_shipped_invitation_body_renders_the_three_links(self):
        """Render the body this module *ships*, not the one in the database.

        `data/mail_template_data.xml` is `noupdate="1"`, so an existing
        database keeps the template it was installed with and `env.ref(...)`
        here would render last year's copy. Reading the source keeps the test
        honest on any database: what it checks is the block this commit adds,
        and it would fail just as loudly if the block used the wrong root
        expression for the template's model.
        """
        attendee = self.event.attendee_ids.filtered(
            lambda a: a.partner_id == self.partner
        )
        self.assertTrue(attendee, "the invitee should have an attendee row")
        body_src = _shipped_body("calendar_template_meeting_invitation")
        self.assertIn("Add to calendar", body_src, "the block is in the shipped body")

        rendered = self.env["mail.template"]._render_template(
            body_src, "calendar.attendee", attendee.ids, engine="qweb"
        )[attendee.id]

        token = self.event.access_token
        self.assertTrue(token, "rendering the block must have minted a token")
        self.assertIn(f"/calendar/ics/{self.event.id}/{token}", rendered)
        self.assertIn("https://www.google.com/calendar/render?", rendered)
        for vendor in ("apple", "outlook", "google"):
            self.assertIn(
                f"/calendar/static/src/img/{vendor}-calendar-128.png", rendered
            )

    def test_every_shipped_template_uses_the_right_root_expression(self):
        # Three of these templates render against `calendar.attendee` and one
        # against `calendar.event`, so the block cannot be copied between them
        # unchanged. Getting this wrong renders an empty href rather than
        # raising, which is why it is asserted rather than left to review.
        for xml_id, expected in (
            ("calendar_template_meeting_invitation", "object.event_id"),
            ("calendar_template_meeting_changedate", "object.event_id"),
            ("calendar_template_meeting_reminder", "object.event_id"),
            ("calendar_template_meeting_update", "object"),
        ):
            with self.subTest(template=xml_id):
                body = _shipped_body(xml_id)
                self.assertIn(f"{{{{ {expected}.id }}}}/", body)
                self.assertIn(f"{expected}.google_calendar_url", body)

    def test_ensure_token_mints_once_and_keeps_it(self):
        self.event.access_token = False
        minted = self.event._calendar_event_ensure_token()
        self.assertTrue(minted)
        self.assertEqual(self.event.access_token, minted)
        self.assertEqual(
            self.event._calendar_event_ensure_token(),
            minted,
            "a second call must not rotate a token already handed out by mail",
        )
