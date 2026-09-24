from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessDenied
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestServicePrincipal(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = new_test_user(
            cls.env, login="svc_principal", password="svc_principal_pw"
        )
        cls.service.principal_type = "service"
        cls.person = new_test_user(
            cls.env, login="svc_person", password="svc_person_pw"
        )
        cls.Users = cls.env["res.users"]

    def _login(self, login, password, interactive):
        return self.Users._login(
            {"login": login, "password": password, "type": "password"},
            {"interactive": interactive},
        )

    def test_a_service_principal_never_logs_in_interactively(self):
        self.assertEqual(
            self._login("svc_person", "svc_person_pw", True)["uid"], self.person.id
        )
        with self.assertRaises(AccessDenied):
            self._login("svc_principal", "svc_principal_pw", True)

    def test_it_reaches_the_programmatic_doors_with_an_api_key_only(self):
        with self.assertRaises(AccessDenied):
            self._login("svc_principal", "svc_principal_pw", False)
        key = (
            self.env["res.users.apikeys"]
            .with_user(self.service)
            ._generate("rpc", "service", fields.Datetime.now() + timedelta(hours=1))
        )
        auth = self._login("svc_principal", key, False)
        self.assertEqual(
            (auth["uid"], auth["auth_method"]), (self.service.id, "apikey")
        )
        with self.assertRaises(AccessDenied):
            self._login("svc_principal", key, True)
