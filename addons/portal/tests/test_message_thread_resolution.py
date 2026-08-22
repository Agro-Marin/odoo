from odoo.tests import TransactionCase, tagged

from odoo.addons.portal.utils import get_portal_partner, resolve_message_thread


@tagged("-at_install", "post_install")
class TestMessageThreadResolution(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Thread Resolution"})

    def _message(self, model, res_id):
        message = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": self.partner.id,
                "body": "<p>body</p>",
                "message_type": "comment",
            }
        )
        self.env.cr.execute(
            "UPDATE mail_message SET model = %s, res_id = %s WHERE id = %s",
            (model or None, res_id, message.id),
        )
        message.invalidate_recordset(["model", "res_id"])
        return message

    def test_is_thread_model(self):
        currency = self.env["res.currency"].search([], limit=1)
        self.assertTrue(
            self._message("res.partner", self.partner.id)._is_thread_model()
        )
        self.assertFalse(self._message("res.currency", currency.id)._is_thread_model())
        self.assertFalse(
            self._message("x.module.was.uninstalled", 1)._is_thread_model()
        )
        self.assertFalse(self._message(False, 1)._is_thread_model())

    def test_get_thread_model_falls_back_to_the_mixin(self):
        currency = self.env["res.currency"].search([], limit=1)
        for model, res_id in (
            ("res.currency", currency.id),
            ("x.module.was.uninstalled", 1),
            (False, 1),
        ):
            with self.subTest(model=model):
                fallback = self._message(model, res_id)._get_thread_model()
                self.assertEqual(fallback._name, "mixin.mail.thread")
                self.assertTrue(fallback._get_allowed_access_params())
        live = self._message("res.partner", self.partner.id)._get_thread_model()
        self.assertEqual(live._name, "res.partner")

    def test_resolve_message_thread_returns_empty_for_unusable_models(self):
        currency = self.env["res.currency"].search([], limit=1)
        for model, res_id in (
            ("res.currency", currency.id),
            ("x.module.was.uninstalled", 1),
            (False, 1),
            ("res.partner", 0),
        ):
            with self.subTest(model=model, res_id=res_id):
                thread = resolve_message_thread(self._message(model, res_id))

                self.assertFalse(thread)
                self.assertEqual(thread._name, "mixin.mail.thread")

    def test_resolve_message_thread_returns_the_record(self):
        thread = resolve_message_thread(self._message("res.partner", self.partner.id))

        self.assertEqual(thread, self.partner)

    def test_credentials_against_an_unusable_thread_are_simply_false(self):
        currency = self.env["res.currency"].search([], limit=1)
        for model, res_id in (
            ("res.currency", currency.id),
            ("x.module.was.uninstalled", 1),
        ):
            for credentials in (
                {"_hash": "deadbeef" * 8, "pid": self.partner.id, "token": None},
                {"_hash": None, "pid": None, "token": "deadbeef" * 8},
            ):
                with self.subTest(model=model, **credentials):
                    thread = resolve_message_thread(self._message(model, res_id))

                    partner = get_portal_partner(thread, **credentials)

                    self.assertFalse(partner)
                    self.assertEqual(partner._name, "res.partner")

    def test_portal_format_reports_no_thread_for_unusable_models(self):
        messages = self._message("x.module.was.uninstalled", 1) | self._message(
            "res.partner", self.partner.id
        )

        formatted = {
            values["id"]: values
            for values in messages._portal_message_format({"id", "model", "res_id"})
        }

        stale, live = messages
        self.assertFalse(formatted[stale.id]["thread"]["has_mail_thread"])
        self.assertTrue(formatted[live.id]["thread"]["has_mail_thread"])
