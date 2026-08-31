"""The form warning about attendees who have no email address.

`invalid_email_partner_ids` is computed already and each attendee tag already
carries a bare "no email" marker (`static/src/views/fields/attendee_tags_list.xml`).
What no view said out loud is the consequence: those people will not be invited.

Kept in its own file because `test_calendar.py` predates the fork's ruff-format
hook and touching it rewrites eight hundred unrelated lines.
"""

from odoo.tests import Form, common

MAIN_FORM = "calendar.view_calendar_event_form"
QUICK_CREATE_FORM = "calendar.view_calendar_event_form_quick_create"


class TestInvalidEmailWarning(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.no_email = cls.env["res.partner"].create({"name": "Attendee Without Mail"})
        cls.with_email = cls.env["res.partner"].create(
            {"name": "Attendee With Mail", "email": "attendee@test.lan"}
        )

    def _warning_is_shown(self, view, partner):
        """Whether the warning block renders, for an event inviting `partner`.

        The block is the only thing that makes `invalid_email_partner_ids`
        conditionally visible: while the field was declared `invisible="1"`,
        this reads True for nobody.
        """
        with Form(self.env["calendar.event"], view=view) as form:
            form.name = "Business Lunch"
            form.partner_ids.add(partner)
            return not form._get_modifier("invalid_email_partner_ids", "invisible")

    def test_main_form_warns_when_an_attendee_has_no_email(self):
        self.assertTrue(
            self._warning_is_shown(MAIN_FORM, self.no_email),
            "the meeting form should warn that an attendee without an email "
            "will not be invited",
        )

    def test_main_form_stays_quiet_when_every_attendee_has_an_email(self):
        self.assertFalse(
            self._warning_is_shown(MAIN_FORM, self.with_email),
            "no warning is due when every attendee can actually be invited",
        )

    def test_quick_create_warns_when_an_attendee_has_no_email(self):
        self.assertTrue(
            self._warning_is_shown(QUICK_CREATE_FORM, self.no_email),
            "the quick-create popover should carry the same warning as the form",
        )

    def test_quick_create_stays_quiet_when_every_attendee_has_an_email(self):
        self.assertFalse(
            self._warning_is_shown(QUICK_CREATE_FORM, self.with_email),
            "no warning is due when every attendee can actually be invited",
        )
