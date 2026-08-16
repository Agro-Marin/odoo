from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCredentialAccessLogImmutability(TransactionCase):
    def _log(self):
        return self.env["credential.access.log"].create(
            {"operation": "read", "credential_name": "My Credential"}
        )

    def test_write_protected_field_is_blocked(self):
        log = self._log()
        with self.assertRaises(UserError):
            log.write({"credential_name": "Tampered"})

    def test_unlink_is_blocked(self):
        log = self._log()
        with self.assertRaises(UserError):
            log.unlink()

    def test_display_name_composition(self):
        log = self._log()
        self.assertIn("My Credential", log.display_name)
        self.assertIn("read", log.display_name)

    def test_display_name_falls_back_to_deleted_label(self):
        log = self.env["credential.access.log"].create({"operation": "use"})
        self.assertIn("(deleted)", log.display_name)
