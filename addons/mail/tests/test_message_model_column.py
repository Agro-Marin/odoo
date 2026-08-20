import json

from odoo.tests import HttpCase, tagged


@tagged("-at_install", "post_install")
class TestMessageModelColumn(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency = cls.env["res.currency"].search([], limit=1)

    def _message_pointing_at(self, model, res_id):
        message = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": self.env.user.partner_id.id,
                "body": "<p>body</p>",
                "message_type": "comment",
                "subtype_id": self.env.ref("mail.mt_comment").id,
            }
        )
        self.env.cr.execute(
            "UPDATE mail_message SET model = %s, res_id = %s WHERE id = %s",
            (model or None, res_id, message.id),
        )
        message.invalidate_recordset(["model", "res_id"])
        self.env.flush_all()
        return message

    def _anonymous_jsonrpc(self, route, params):
        response = self.url_open(
            route,
            data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": params}),
            headers={"Content-Type": "application/json"},
        )
        return response.json()

    def _assert_not_found(self, payload, route, params):
        error = payload.get("error") or {}
        self.assertNotEqual(
            error.get("data", {}).get("name"),
            "builtins.AttributeError",
            f"{route} raised AttributeError on {params}: {error.get('data', {}).get('message')}",
        )
        self.assertEqual(error.get("code"), 404, f"{route} did not answer 404: {error}")

    def test_reaction_route_denies_unusable_models(self):
        for model, res_id in (
            ("res.currency", self.currency.id),
            ("x.module.was.uninstalled", 1),
        ):
            with self.subTest(model=model):
                message = self._message_pointing_at(model, res_id)
                params = {
                    "message_id": message.id,
                    "content": "\U0001f44d",
                    "action": "add",
                }
                payload = self._anonymous_jsonrpc("/mail/message/reaction", params)

                self._assert_not_found(payload, "/mail/message/reaction", params)

    def test_update_content_route_denies_unusable_models(self):
        for model, res_id in (
            ("res.currency", self.currency.id),
            ("x.module.was.uninstalled", 1),
        ):
            with self.subTest(model=model):
                message = self._message_pointing_at(model, res_id)
                params = {
                    "message_id": message.id,
                    "update_data": {"body": "<p>edited</p>"},
                }
                payload = self._anonymous_jsonrpc(
                    "/mail/message/update_content", params
                )

                self._assert_not_found(payload, "/mail/message/update_content", params)

    def test_predicate_and_fallback(self):
        live = self._message_pointing_at("res.partner", self.env.user.partner_id.id)
        self.assertTrue(live._is_thread_model())
        self.assertEqual(live._get_thread_model()._name, "res.partner")

        for model, res_id in (
            ("res.currency", self.currency.id),
            ("x.module.was.uninstalled", 1),
            (False, 1),
        ):
            with self.subTest(model=model):
                message = self._message_pointing_at(model, res_id)

                self.assertFalse(message._is_thread_model())
                fallback = message._get_thread_model()
                self.assertEqual(fallback._name, "mixin.mail.thread")
                self.assertIsInstance(fallback._get_allowed_access_params(), set)
