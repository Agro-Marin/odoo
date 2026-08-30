from odoo import Command
from odoo.exceptions import AccessDenied, UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPhoneBlacklistOps(TransactionCase):
    """phone.blacklist add / remove / reactivate / search behaviour."""

    NUMBER = "+33612345678"

    @property
    def Blacklist(self):
        return self.env["phone.blacklist"]

    def test_add_creates_active_entry(self):
        """add() blacklists a sanitized, active number."""
        entry = self.Blacklist.add(self.NUMBER)
        self.assertTrue(entry.active)
        self.assertEqual(entry.number, self.NUMBER)

    def test_add_existing_reactivates(self):
        """Re-adding an archived number reactivates the same record."""
        entry = self.Blacklist.add(self.NUMBER)
        entry.action_archive()
        self.assertFalse(entry.active)
        again = self.Blacklist.add(self.NUMBER)
        self.assertEqual(again, entry)
        self.assertTrue(again.active)

    def test_remove_archives_entry(self):
        """remove() de-activates an existing blacklist entry."""
        self.Blacklist.add(self.NUMBER)
        removed = self.Blacklist.remove(self.NUMBER)
        self.assertFalse(removed.active)

    def test_remove_unknown_number_creates_inactive(self):
        """Removing a not-yet-listed number records it as inactive (boundary)."""
        removed = self.Blacklist.remove("+33698765432")
        self.assertTrue(removed)
        self.assertFalse(removed.active)

    def test_search_number_sanitizes_value(self):
        """Searching by number matches the sanitized entry."""
        entry = self.Blacklist.add(self.NUMBER)
        found = self.Blacklist.search([("number", "=", self.NUMBER)])
        self.assertIn(entry, found)

    def test_action_blacklist_remove_opens_wizard(self):
        """The unblacklist action targets the remove wizard."""
        entry = self.Blacklist.add(self.NUMBER)
        action = entry.phone_action_blacklist_remove()
        self.assertEqual(action["res_model"], "phone.blacklist.remove")

    def test_create_invalid_number_raises(self):
        """Creating a blacklist entry with an unparseable number is rejected."""
        with self.assertRaises(UserError):
            self.Blacklist.create([{"number": "12"}])

        self.assertFalse(self.Blacklist.search([("number", "=", "12")]))


@tagged("post_install", "-at_install")
class TestPhoneBlacklistDoesNotDeriveFromActingUser(TransactionCase):
    """A falsy/unparseable number must never resolve to env.user's own.

    ``_phone_format``'s "no number given" fallback is meant for a record
    looking up its own field; ``phone.blacklist`` misuses it by sanitizing
    through ``self.env.user._phone_format(...)``, where ``self`` (the
    acting user) is unrelated to the entry being created/searched/removed.
    Every method must reject a falsy/unparseable number outright instead of
    silently substituting the acting user's own phone/mobile.
    """

    @property
    def Blacklist(self):
        return self.env["phone.blacklist"]

    def setUp(self):
        super().setUp()
        self.env.user.write({"phone": "+32485001122", "mobile": False})

    def test_create_with_falsy_number_raises(self):
        with self.assertRaises(UserError):
            self.Blacklist.create([{"number": False}])
        self.assertFalse(self.Blacklist.search([("number", "=", "+32485001122")]))

    def test_write_with_falsy_number_raises(self):
        entry = self.Blacklist.add("+33612345678")
        with self.assertRaises(UserError):
            entry.write({"number": False})

    def test_search_number_with_falsy_value_raises(self):
        with self.assertRaises(UserError):
            self.Blacklist.search([("number", "=", "")])

    def test_add_with_unparseable_number_raises(self):
        with self.assertRaises(UserError):
            self.Blacklist.add("garbage-not-a-number")
        self.assertFalse(self.Blacklist.search([("number", "=", "+32485001122")]))

    def test_remove_with_unparseable_number_raises(self):
        with self.assertRaises(UserError):
            self.Blacklist.remove("garbage-not-a-number")
        self.assertFalse(self.Blacklist.search([("number", "=", "+32485001122")]))


@tagged("post_install", "-at_install")
class TestPortalUserBlacklistOnDeactivate(TransactionCase):
    """Deactivating a portal user optionally blacklists their phone."""

    def test_deactivation_with_request_blacklists_phone(self):
        user = self.env["res.users"].create(
            {
                "name": "Blacklist victim",
                "login": "blacklist.victim@test.example.com",
                "phone": "+33699887766",
                "group_ids": [Command.set([self.env.ref("base.group_portal").id])],
            },
        )
        user._deactivate_portal_user(request_blacklist=True)

        entry = self.env["phone.blacklist"].search([("number", "=", "+33699887766")])
        self.assertTrue(entry.active)

    def test_deactivation_without_request_keeps_phone_clean(self):
        user = self.env["res.users"].create(
            {
                "name": "Clean victim",
                "login": "clean.victim@test.example.com",
                "phone": "+33688776655",
                "group_ids": [Command.set([self.env.ref("base.group_portal").id])],
            },
        )
        user._deactivate_portal_user()

        self.assertFalse(
            self.env["phone.blacklist"].search([("number", "=", "+33688776655")])
        )

    def test_deactivation_of_internal_user_denied(self):
        """Self-service deactivation of a non-portal user is denied."""
        user = self.env["res.users"].create(
            {
                "name": "Internal user",
                "login": "internal.deactivate@test.example.com",
                "phone": "+33611223344",
            },
        )

        with self.assertRaises(AccessDenied):
            user._deactivate_portal_user(request_blacklist=True)

        self.assertFalse(
            self.env["phone.blacklist"].search([("number", "=", "+33611223344")])
        )
