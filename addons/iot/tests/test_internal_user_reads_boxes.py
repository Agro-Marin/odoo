from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestAnInternalUserReadsBoxes(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.box = cls.env["iot.box"].create(
            {"name": "Till box", "identifier": "till-box", "ip": "10.1.2.4"}
        )
        cls.scanner = cls.env["iot.device"].create(
            {
                "name": "Till scanner",
                "identifier": "till-scanner",
                "iot_id": cls.box.id,
                "type": "scanner",
            }
        )
        cls.other_device = cls.env["device.device"].create(
            {"name": "Yard tracker", "identifier": "yard-tracker"}
        )
        cls.user = new_test_user(cls.env, login="till_clerk", groups="base.group_user")

    def test_an_internal_user_reads_a_box_and_its_devices_through_the_registry(self):
        box = self.box.with_user(self.user)
        scanner = self.scanner.with_user(self.user)
        self.assertEqual(box.read(["name", "identifier"])[0]["name"], "Till box")
        self.assertEqual(
            scanner.read(["name", "identifier", "iot_id"])[0]["identifier"],
            "till-scanner",
        )

    def test_an_internal_user_still_cannot_read_other_registry_rows(self):
        self.assertFalse(self.user.has_group("device.group_device_user"))
        with self.assertRaises(AccessError):
            self.other_device.with_user(self.user).read(["name"])
