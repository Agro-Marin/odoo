"""Regression tests for the eighth mail hardening audit.

Each test pins a specific, empirically-confirmed finding so a future refactor
cannot silently reintroduce it. Coverage:

 - ``_get_mail_batch_size`` must treat a *negative* ``mail.batch_size`` ICP as
   malformed (like a non-integer / zero) and fall back to the default: a
   negative value is truthy, so ``batch_size or default`` let it through and
   ``itertools.batched(res_ids, -5)`` raised "n must be at least one", aborting
   every mass-send loop;
 - ``mail.message.create`` with a tracking-value command list that mixes
   ``(0, 0, vals)`` (create) with other commands must not create the (0, 0)
   entries twice;
 - ``mail.mail.send(raise_exception=True)`` must raise when the only recipient
   is invalid/missing instead of silently returning as if the mail was sent;
 - ``_render_field`` must reuse a caller-supplied ``res_ids_lang`` instead of
   recomputing the lang template via ``_classify_per_lang`` (the mass-mail
   composer was rendering the lang expression 5x per batch);
 - ``mail.message._to_store`` must not mutate the caller's ``fields`` list.
"""

from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.base.models.ir_mail_server import (
    MailDeliveryException,
    OutgoingEmailError,
)
from odoo.addons.mail.tests.common import MailCommon, mail_new_test_user
from odoo.addons.mail.tools.discuss import Store


@tagged("-at_install", "post_install", "mail_hardening_v8")
class TestMailHardeningV8(MailCommon):
    def test_get_mail_batch_size_rejects_negative(self):
        """A negative ICP is as malformed as a garbage/zero one -> default."""
        template = self.env["mail.template"]
        icp = self.env["ir.config_parameter"].sudo()
        for raw, expected in [
            ("-5", 50),
            ("-1", 50),
            ("0", 50),
            ("garbage", 50),
            ("", 50),
            ("10", 10),
        ]:
            icp.set_param("mail.batch_size", raw)
            self.assertEqual(
                template._get_mail_batch_size(),
                expected,
                f"mail.batch_size={raw!r} should resolve to {expected}",
            )

    def test_tracking_values_no_double_create_on_mixed_commands(self):
        """(0, 0, vals) tracking commands mixed with a (4, id) link must be
        created exactly once, not twice."""
        partner = self.env.user.partner_id
        field = self.env["ir.model.fields"].search(
            [("model", "=", "res.partner"), ("name", "=", "name")], limit=1
        )
        seed_msg = self.env["mail.message"].create(
            {"subject": "seed", "model": "res.partner", "res_id": partner.id}
        )
        seed_tv = self.env["mail.tracking.value"].create(
            {
                "field_id": field.id,
                "mail_message_id": seed_msg.id,
                "old_value_char": "a",
                "new_value_char": "b",
            }
        )
        message = self.env["mail.message"].create(
            {
                "subject": "mix",
                "model": "res.partner",
                "res_id": partner.id,
                "tracking_value_ids": [
                    (0, 0, {"field_id": field.id,
                            "old_value_char": "x", "new_value_char": "y"}),
                    (4, seed_tv.id),
                ],
            }
        )
        self.assertEqual(
            len(message.tracking_value_ids),
            2,
            "the (0, 0, vals) tracking value must be created once, not twice",
        )

    def test_send_raises_on_only_invalid_recipient(self):
        """send(raise_exception=True) must surface a hard failure when no
        recipient could be delivered to (NO_VALID_RECIPIENT)."""
        IrMailServer = type(self.env["ir.mail_server"])

        class _DummySession:
            def quit(self):
                pass

            def close(self):
                pass

        def _raise_no_recipient(self, message, *args, **kwargs):
            raise OutgoingEmailError(IrMailServer.NO_VALID_RECIPIENT)

        mail = self.env["mail.mail"].create(
            {
                "email_from": "sender@example.com",
                "email_to": "this-is-not-an-email",
                "subject": "hardening v8",
                "body_html": "<p>hi</p>",
            }
        )
        # The mock drives the real NO_VALID_RECIPIENT path (send_email raises it
        # once the connection is established). Before the fix, _send caught it,
        # set failure_type, but never re-raised for a strict caller -> send()
        # returned as if it had succeeded. The contract under test is simply that
        # a total failure is surfaced (the persisted state is the caller's to
        # roll back, so it is intentionally not asserted here).
        with (
            patch.object(IrMailServer, "_connect__",
                         lambda self, *a, **k: _DummySession()),
            patch.object(IrMailServer, "_disable_send", lambda self: False),
            patch.object(IrMailServer, "send_email", _raise_no_recipient),
        ):
            with self.assertRaises(MailDeliveryException):
                mail.send(raise_exception=True)

    def test_render_field_reuses_provided_res_ids_lang(self):
        """When res_ids_lang is supplied, _render_field must not recompute the
        lang via _classify_per_lang (avoids the 5x lang render on mass mail)."""
        template = self.env["mail.template"].create(
            {
                "name": "hardening v8",
                "model_id": self.env["ir.model"]._get_id("res.partner"),
                "subject": "Hi {{ object.name }}",
            }
        )
        res_ids = self.env.user.partner_id.ids
        with patch.object(
            type(template),
            "_classify_per_lang",
            side_effect=AssertionError(
                "_render_field must reuse res_ids_lang, not recompute the lang"
            ),
        ):
            rendered = template._render_field(
                "subject", res_ids, compute_lang=True,
                res_ids_lang={res_ids[0]: "en_US"},
            )
        self.assertIn(res_ids[0], rendered)

    def test_incoming_cc_does_not_suppress_inbox_needaction(self):
        """A follower reached as a Cc of the incoming email must still get an
        inbox notification: the email dedup must skip only the *email* channel,
        not drop the recipient from every channel."""
        user = mail_new_test_user(
            self.env,
            login="v8inbox",
            groups="base.group_user",
            notification_type="inbox",
            email="v8inbox@example.com",
            name="V8 Inbox User",
        )
        record = self.env["res.partner"].create({"name": "v8 doc"})
        record.message_subscribe(partner_ids=user.partner_id.ids)
        message = record.message_post(
            body="hi",
            subtype_xmlid="mail.mt_comment",
            author_id=self.env.user.partner_id.id,
        )
        recipients = record._notify_get_recipients(
            message,
            msg_vals={
                "incoming_email_cc": "v8inbox@example.com",
                "subtype_id": self.env.ref("mail.mt_comment").id,
                "message_type": "comment",
                "author_id": self.env.user.partner_id.id,
            },
        )
        inbox = [
            r for r in recipients
            if r["id"] == user.partner_id.id and r["notif"] == "inbox"
        ]
        self.assertTrue(
            inbox,
            "an inbox follower Cc'd on the incoming email must still be notified "
            "in Inbox (only the duplicate email should be skipped)",
        )

    def test_to_store_does_not_mutate_fields_arg(self):
        """_to_store both removes 'message_format' and appends 'starred'; it must
        do so on its own copy, never on the caller's list."""
        message = self.env["mail.message"].create(
            {
                "subject": "hardening v8",
                "model": "res.partner",
                "res_id": self.env.user.partner_id.id,
            }
        )
        fields_arg = ["message_format"]
        message._to_store(Store(), fields_arg)
        self.assertEqual(
            fields_arg,
            ["message_format"],
            "the caller's fields list must not be mutated by _to_store",
        )
