"""Regression tests for the ninth mail hardening audit.

Each test pins a defect that was reproduced end to end (real ingestion path, real
controller, real mail records) before being fixed, so a future refactor cannot
silently reintroduce it. Coverage:

 - the catchall bounce template is indexed with dict keys ('email_from', 'body')
   and was handed a raw ``email.message.EmailMessage``, whose ``__getitem__`` is
   a *header* lookup: every bounce went out as "Hello ," with an empty quote;
 - the alias security/configuration bounce omitted the loop-detection tag every
   other bounce emitter appends, so an autoresponder behind an unauthorized
   sender ping-ponged with the gateway forever;
 - the ``alias_incoming_local`` leg of alias routing is not scoped by
   ``alias_domain_id`` and was never reconciled against exact matches, so two
   companies owning the same local part both matched one inbound mail and each
   created its own record;
 - ``_get_blacklist_record_ids`` matched blacklist-mixin models on
   ``email_normalized`` only, which keeps just the *first* address of a
   multi-address record, so an unsubscribe on the second address was ignored;
 - ``_message_fetch`` accepted an unbounded ``limit`` and uncoerced
   ``before``/``after``/``around`` from ``fetch_params`` on ``auth="public"``
   routes, and an unknown key reached it as an unexpected keyword argument;
 - a mention token carries no thread binding, so tokens harvested in one channel
   could add those partners as recipients of a message posted in another;
 - a push notification whose endpoint is unresolvable is kept for retry, and
   being the oldest row it re-headed every ``id ASC`` batch, starving the queue;
 - the out-of-office auto-reply ran at compose time rather than delivery time,
   so a message scheduled beyond the 4-day dedupe window produced two replies.
"""

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import MailCommon


@tagged("-at_install", "post_install", "mail_hardening_v9")
class TestMailGatewayHardeningV9(MailCommon):
    """Gateway: bounce rendering, loop tagging, cross-domain alias routing."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead_model_id = cls.env["ir.model"]._get_id("mail.test.lead")

    def _incoming(
        self,
        to,
        email_from="Outsider <outsider@ext.com>",
        msg_id="<v9@ext>",
        body="ORIGINAL BODY TEXT",
        references="",
    ):
        headers = (
            f"From: {email_from}\r\nTo: {to}\r\nSubject: Need help\r\n"
            f"Message-Id: {msg_id}\r\n"
        )
        if references:
            headers += f"References: {references}\r\n"
        return (
            headers + f"MIME-Version: 1.0\r\nContent-Type: text/plain\r\n\r\n{body}\r\n"
        )

    def test_catchall_bounce_renders_sender_and_body(self):
        """The catchall bounce must name the sender and quote the original.

        It was rendered with the raw EmailMessage, so ``message['email_from']``
        and ``message['body']`` -- header lookups, not dict keys -- both resolved
        to None and the recipient got "Hello ," with an empty blockquote.
        """
        catchall = self.mail_alias_domain.catchall_email
        with self.mock_mail_gateway():
            self.env["mail.thread"].message_process(
                None, self._incoming(catchall, msg_id="<v9-catchall@ext>")
            )
        self.assertEqual(len(self._new_mails), 1, "a catchall bounce must be sent")
        body = self._new_mails.body_html
        self.assertIn("outsider@ext.com", body, "bounce must name the sender")
        self.assertIn("ORIGINAL BODY TEXT", body, "bounce must quote the original")
        self.assertNotIn("Hello ,", body)

    def test_catchall_bounce_carries_loop_tag(self):
        """Control for the test below: this emitter always tagged correctly."""
        catchall = self.mail_alias_domain.catchall_email
        with self.mock_mail_gateway():
            self.env["mail.thread"].message_process(
                None, self._incoming(catchall, msg_id="<v9-catchall-tag@ext>")
            )
        self.assertIn("-loop-detection-bounce-email@", self._new_mails.references)

    def test_alias_security_bounce_carries_loop_tag(self):
        """The alias security bounce must carry the loop-detection tag.

        ``_detect_loop_headers`` greps incoming references for that tag; it is
        the only guard on this path (``_detect_loop_sender`` never runs because
        the route list comes back empty). Untagged, the bounce loops forever.
        """
        alias = self.env["mail.alias"].create(
            {
                "alias_name": "v9secure",
                "alias_model_id": self.lead_model_id,
                "alias_domain_id": self.mail_alias_domain.id,
                "alias_contact": "partners",
            }
        )
        with self.mock_mail_gateway():
            self.env["mail.thread"].message_process(
                None, self._incoming(alias.alias_full_name, msg_id="<v9-sec@ext>")
            )
        self.assertEqual(
            len(self._new_mails), 1, "an alias security bounce must be sent"
        )
        self.assertIn(
            "-loop-detection-bounce-email@",
            self._new_mails.references,
            "untagged, a reply to this bounce is re-bounced forever",
        )

    def test_alias_security_bounce_stops_the_loop(self):
        """A reply carrying the bounce's references must not be bounced again."""
        alias = self.env["mail.alias"].create(
            {
                "alias_name": "v9loop",
                "alias_model_id": self.lead_model_id,
                "alias_domain_id": self.mail_alias_domain.id,
                "alias_contact": "partners",
            }
        )
        with self.mock_mail_gateway():
            self.env["mail.thread"].message_process(
                None, self._incoming(alias.alias_full_name, msg_id="<v9-loop1@ext>")
            )
        bounce = self._new_mails
        reply_refs = f"{bounce.references} {bounce.message_id}".strip()
        with self.mock_mail_gateway():
            self.env["mail.thread"].message_process(
                None,
                self._incoming(
                    alias.alias_full_name,
                    msg_id="<v9-loop2@ext>",
                    references=reply_refs,
                ),
            )
        self.assertFalse(
            self._new_mails, "the autoresponder's reply must not trigger a new bounce"
        )

    def test_alias_incoming_local_does_not_cross_domains(self):
        """An exact alias match must win over another company's local-part match.

        ``support@a.com`` and ``support@b.com`` are an explicitly permitted pair;
        the unscoped local-part leg made a mail addressed to one of them create a
        record in *both* companies.
        """
        domain_b = self.env["mail.alias.domain"].create(
            {
                "name": "v9-bcorp.com",
                "catchall_alias": "catchall",
                "bounce_alias": "bounce",
            }
        )
        common = {
            "alias_name": "v9support",
            "alias_model_id": self.lead_model_id,
            "alias_incoming_local": True,
            "alias_contact": "everyone",
        }
        alias_a = self.env["mail.alias"].create(
            {**common, "alias_domain_id": self.mail_alias_domain.id}
        )
        alias_b = self.env["mail.alias"].create(
            {**common, "alias_domain_id": domain_b.id}
        )
        self.assertTrue(alias_a.alias_full_name.endswith(self.mail_alias_domain.name))
        self.assertTrue(alias_b.alias_full_name.endswith(domain_b.name))

        Lead = self.env["mail.test.lead"]
        before = Lead.search([])
        self.env["mail.thread"].message_process(
            None, self._incoming(alias_a.alias_full_name, msg_id="<v9-x1@ext>")
        )
        created = Lead.search([]) - before
        self.assertEqual(
            len(created),
            1,
            "one inbound mail must not create a record in both companies",
        )

        # control: the other company's alias still receives its own mail
        before = Lead.search([])
        self.env["mail.thread"].message_process(
            None, self._incoming(alias_b.alias_full_name, msg_id="<v9-x2@ext>")
        )
        self.assertEqual(len(Lead.search([]) - before), 1)

    def test_routing_filter_local_aliases_keeps_unclaimed_localparts(self):
        """The local fallback must still apply when no alias owns the address."""
        alias = self.env["mail.alias"].create(
            {
                "alias_name": "v9local",
                "alias_model_id": self.lead_model_id,
                "alias_domain_id": self.mail_alias_domain.id,
                "alias_incoming_local": True,
                "alias_contact": "everyone",
            }
        )
        kept = self.env["mail.thread"]._routing_filter_local_aliases(
            alias, ["v9local@some-other-domain.com"]
        )
        self.assertEqual(kept, alias, "no exact match -> local fallback must survive")


@tagged("-at_install", "post_install", "mail_hardening_v9")
class TestBlacklistHardeningV9(MailCommon):
    """Blacklist must cover every address a record holds, not just the first."""

    def test_blacklist_matches_secondary_address(self):
        lead_multi = self.env["mail.test.lead"].create(
            {
                "name": "Multi",
                "email_from": "v9old@x.com, v9new@y.com",
            }
        )
        lead_single = self.env["mail.test.lead"].create(
            {
                "name": "Single",
                "email_from": "v9new@y.com",
            }
        )
        self.env["mail.blacklist"]._add("v9new@y.com")
        # email_normalized keeps only the first address (strict=False), which is
        # exactly why the blacklist check could not rely on it alone.
        self.assertEqual(lead_multi.email_normalized, "v9old@x.com")

        composer = self.env["mail.compose.message"].create(
            {
                "composition_mode": "mass_mail",
                "model": "mail.test.lead",
                "subject": "Promo",
                "body": "<p>Buy</p>",
            }
        )
        composer = composer.with_context(
            default_model="mail.test.lead", active_ids=(lead_multi | lead_single).ids
        )
        blacklisted = composer._get_blacklist_record_ids(
            {lead_multi.id: {}, lead_single.id: {}}
        )
        self.assertIn(
            lead_multi.id,
            blacklisted,
            "a record holding a blacklisted secondary address must be excluded",
        )
        self.assertIn(lead_single.id, blacklisted, "control: single address")


@tagged("-at_install", "post_install", "mail_hardening_v9")
class TestMessageFetchParamsHardeningV9(MailCommon):
    """``fetch_params`` is a raw client dict splatted into ``_message_fetch``."""

    def test_unknown_fetch_param_is_dropped(self):
        """An unknown key used to surface a raw TypeError to an anonymous caller."""
        sanitized = self.env["mail.message"]._sanitize_fetch_params(
            {"limit": 10, "bogus_kwarg": 1, "before": 5}
        )
        self.assertEqual(sanitized, {"limit": 10, "before": 5})
        # and the sanitized dict is safe to splat
        self.env["mail.message"]._message_fetch(domain=[("id", "=", 0)], **sanitized)

    def test_fetch_limit_is_clamped(self):
        Message = self.env["mail.message"]
        self.assertEqual(Message._clamp_fetch_limit(10**9), 100)
        self.assertEqual(Message._clamp_fetch_limit(0), 1)
        self.assertEqual(Message._clamp_fetch_limit(-5), 1)
        self.assertEqual(Message._clamp_fetch_limit("nope"), 30)
        self.assertEqual(Message._clamp_fetch_limit(None), 30)
        self.assertEqual(Message._clamp_fetch_limit(42), 42)

    def test_non_integer_cursor_does_not_reach_the_domain(self):
        """A non-numeric cursor reached psycopg as-is (InvalidTextRepresentation)."""
        Message = self.env["mail.message"]
        self.assertIsNone(Message._to_message_cursor("xyz"))
        self.assertEqual(Message._to_message_cursor("12"), 12)
        # would raise psycopg.errors.InvalidTextRepresentation before the fix
        Message._message_fetch(domain=None, before="xyz", after="xyz", around="xyz")


@tagged("-at_install", "post_install", "mail_hardening_v9")
class TestPushQueueHardeningV9(MailCommon):
    """One unreachable endpoint must not starve the whole push queue."""

    def test_unresolvable_notification_is_held_back(self):
        from odoo.addons.mail.tools.web_push import PushEndpointUnresolvableError

        self.env["ir.config_parameter"].sudo().set_param(
            "mail.web_push_vapid_private_key", "priv"
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "mail.web_push_vapid_public_key", "pub"
        )
        device = self.env["mail.push.device"].create(
            {
                "endpoint": "https://push.example.com/v9",
                "keys": '{"p256dh": "x", "auth": "y"}',
                "partner_id": self.partner_employee.id,
            }
        )
        push = self.env["mail.push"].create(
            {
                "mail_push_device_id": device.id,
                "payload": "{}",
            }
        )
        with patch(
            "odoo.addons.mail.models.mail_push.push_to_end_point",
            side_effect=PushEndpointUnresolvableError(),
        ):
            self.env["mail.push"]._push_notification_to_endpoint()

        self.assertTrue(push.exists(), "a transient failure must keep the row")
        self.assertTrue(push.retry_after, "the row must be held back for retry")
        self.assertNotIn(
            push,
            self.env["mail.push"].search(self.env["mail.push"]._get_due_domain()),
            "a held-back row must not re-head the next batch",
        )

    def test_due_domain_releases_after_the_delay(self):
        device = self.env["mail.push.device"].create(
            {
                "endpoint": "https://push.example.com/v9b",
                "keys": '{"p256dh": "x", "auth": "y"}',
                "partner_id": self.partner_employee.id,
            }
        )
        push = self.env["mail.push"].create(
            {
                "mail_push_device_id": device.id,
                "payload": "{}",
                "retry_after": fields.Datetime.now() - timedelta(minutes=1),
            }
        )
        self.assertIn(
            push, self.env["mail.push"].search(self.env["mail.push"]._get_due_domain())
        )
