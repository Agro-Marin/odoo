"""``mail.message.model`` is free-form; the public chatter routes must survive it.

The column is a plain ``Char`` with no foreign key and no constraint, so it can
hold two values that no access path may dereference blindly:

* the name of a model whose module has been uninstalled -- messages outlive
  their model, so ``env[name]`` is a ``KeyError``;
* the name of a live model that never inherited ``mail.thread`` -- every
  ``mail.thread`` method the access path calls on it is an ``AttributeError``.

Only the first was guarded. The second answered ``/mail/message/reaction`` and
``/mail/message/update_content`` -- both ``auth="public"`` -- with
``AttributeError: 'res.currency' object has no attribute
'_get_allowed_access_params'``: an HTTP 500 carrying a model name to an
unauthenticated caller. These tests pin both to the same answer a message with
no usable thread deserves, which is 404.
"""

import json

from odoo.tests import HttpCase, tagged


@tagged("-at_install", "post_install")
class TestMessageModelColumn(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency = cls.env["res.currency"].search([], limit=1)

    def _message_pointing_at(self, model, res_id):
        """A message whose ``model`` names ``model``, written past the ORM.

        ``create`` resolves ``reply_to`` *through* the model, so a row naming a
        model that is not in the registry cannot be built with the ORM at all --
        which is exactly why the writer never produced this state and the reader
        was never taught to expect it.
        """
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
        """Call ``route`` with no session at all, returning the parsed answer."""
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
        """The rule itself, so the routes above are not the only witness."""
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
                self.assertEqual(fallback._name, "mail.thread")
                # The fallback exists so mail.thread class methods stay callable.
                self.assertTrue(fallback._get_allowed_access_params())
