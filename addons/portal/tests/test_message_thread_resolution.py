"""``mail.message.model`` is free-form; the portal chatter must survive that.

Nothing constrains that column to a model that is still installed, nor to one
that inherits ``mail.thread``. Portal has three places that dereference it — one
formatter and two controller overrides that resolve the thread purely to check a
portal credential against it — and only the formatter used to guard.

The two controller overrides run on ``auth="public"`` routes, so an unguarded
``request.env[message.model]`` is a traceback served to an anonymous caller:
``KeyError`` for a model that is gone, ``AttributeError`` from
``_mail_post_token_field`` for one that is not a thread.
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.portal.utils import get_portal_partner, resolve_message_thread


@tagged("-at_install", "post_install")
class TestMessageThreadResolution(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Thread Resolution"})

    def _message(self, model, res_id):
        """A message pointing wherever we say.

        Written through SQL on purpose: ``mail.message.create`` resolves
        ``reply_to`` *through* the named model, so a row naming a model that is
        not in the registry cannot be built with the ORM at all. That is exactly
        the state the database is left in by an uninstall — the rows outlive the
        model — which is why the reader has to cope with it and the writer never
        produced it.
        """
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
        # A live model that never inherited mail.thread.
        self.assertFalse(self._message("res.currency", currency.id)._is_thread_model())
        # The name of a model whose module has been uninstalled.
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
                self.assertEqual(fallback._name, "mail.thread")
                # The whole point: mail.thread class methods are now reachable.
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
                self.assertEqual(thread._name, "mail.thread")

    def test_resolve_message_thread_returns_the_record(self):
        thread = resolve_message_thread(self._message("res.partner", self.partner.id))

        self.assertEqual(thread, self.partner)

    def test_credentials_against_an_unusable_thread_are_simply_false(self):
        """The whole point: a bad ``model`` must answer "no", not raise.

        Both credential shapes are exercised — a hash+pid pair and a bare token —
        because each reaches ``_mail_post_token_field`` by a different route.
        """
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
        """``has_mail_thread`` drives the chatter's reaction button.

        Formatting a whole page of messages must not fail over one row whose
        model has since been uninstalled.
        """
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
