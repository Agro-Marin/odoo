"""Regression tests for the eleventh mail hardening audit.

Each test pins a defect reproduced end to end before being fixed, so a refactor
cannot silently reintroduce it. Coverage:

 - ``/mail/data`` batches independent fetch params into one round-trip
   (``["failures", "systray_get_activities", "init_messaging"]`` on every boot)
   but ran them without isolation, so a crash in the best-effort ``failures``
   handler discarded messaging init too -- and the client swallowed the
   rejection, leaving the user with no error and no delivery-failure list.
 - the ``failures`` handler dereferenced ``mail.message.model`` -- a plain
   ``Char`` with no constraint -- straight into ``env[model]``. A name that is
   no longer in the registry raised ``KeyError``, which also kept the garbage
   collection right below it from ever reaping the offending row.
 - ``/mail/message/post`` coerced ``attachment_ids`` / ``partner_ids`` with a
   bare ``map(int, ...)``, so an anonymous caller on a public channel could
   raise ``ValueError``/``TypeError`` server-side. Malformed ids must be
   rejected, never trimmed: ``attachment_ids`` is zipped ``strict=True`` against
   ``attachment_tokens``, so dropping one would slide the rest onto their
   neighbour's ownership token.
 - ``read_subscription_data`` neither coerced ``follower_id`` nor guarded
   ``mail.followers.res_model`` (documented as carrying no integrity check).
 - ``_notify_thread_by_inbox`` serialized the message payload once per recipient
   in that recipient's own environment, so ``starred`` and the author's
   ``main_user_id`` each cost one query per recipient: O(N) where the e-mail and
   channel paths are O(1). Both are now resolved in one batch up front.
 - numeric mail ICPs were read with a bare ``int(get_param(...))`` in eight
   places. The stored value is free text typed in Settings, so one stray
   character raised ``ValueError`` inside whichever flow happened to read it --
   losing an incoming e-mail in the gateway, breaking the outgoing-queue cron,
   or a list view. They now share ``ir.config_parameter._get_int_param``, which
   degrades to the documented default and warns.
"""

from contextlib import contextmanager

from odoo.tests import JsonRpcException, tagged
from odoo.tools import mute_logger

from odoo.addons.base.tests.common import HttpCase
from odoo.addons.mail.tests.common import MailCommon, mail_new_test_user


@tagged("-at_install", "post_install", "mail_hardening_v11")
class TestFetchParamIsolationV11(HttpCase, MailCommon):
    def _plant_orphan_failure(self):
        """A bounced notification whose message points at a dead model name.

        The ``failures`` domain filters on ``author_id = <session partner>``, so
        this must be authored by the *authenticated* user (admin), not by
        ``self.env.user`` -- which is root in an HttpCase and would make the
        route never see the row at all.
        """
        author = self.env.ref("base.user_admin").partner_id
        message = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": author.id,
                "message_type": "comment",
                "subject": "v11 orphan",
                "author_id": author.id,
            }
        )
        # write() bypasses the create-time registry lookup: this is exactly how
        # such a row survives in the wild (renaming migrations, direct SQL).
        message.write({"model": "v11.no.such.model"})
        self.env["mail.notification"].create(
            {
                "mail_message_id": message.id,
                "res_partner_id": author.id,
                "author_id": author.id,
                "notification_type": "email",
                "notification_status": "bounce",
            }
        )
        self.env.flush_all()
        return message

    @mute_logger("odoo.addons.mail.controllers.webclient")
    def test_orphan_model_does_not_void_the_batch(self):
        """One unusable notification must not cost the user messaging init."""
        self.authenticate("admin", "admin")
        message = self._plant_orphan_failure()
        result = self.make_jsonrpc_request(
            "/mail/data",
            {"fetch_params": ["failures", "init_messaging"]},
        )
        # init_messaging still answered: the batch was not discarded.
        self.assertTrue(result, "batched fetch params must still return data")
        self.assertIn(
            "Store",
            result,
            "init_messaging must survive a failure in a sibling fetch param",
        )
        # /mail/data is readonly=True so it cannot garbage-collect; the
        # write-capable sibling route must reap the unusable row instead of
        # raising KeyError before ever reaching that cleanup.
        self.make_jsonrpc_request("/mail/action", {"fetch_params": ["failures"]})
        self.assertFalse(
            self.env["mail.notification"]
            .sudo()
            .search([("mail_message_id", "=", message.id)]),
            "a notification on an unknown model must be reaped as lost",
        )

    @mute_logger("odoo.addons.mail.controllers.webclient")
    def test_failing_param_does_not_hide_siblings(self):
        """A handler that raises is logged and skipped, siblings still answer."""
        self.authenticate("admin", "admin")

        from odoo.addons.mail.controllers.webclient import WebclientController

        def boom(cls, store, name, params):
            if name == "failures":
                raise ValueError("v11 induced failure")

        original = WebclientController._process_request_for_logged_in_user
        try:
            WebclientController._process_request_for_logged_in_user = classmethod(boom)
            result = self.make_jsonrpc_request(
                "/mail/data",
                {"fetch_params": ["failures", "init_messaging"]},
            )
        finally:
            WebclientController._process_request_for_logged_in_user = original
        self.assertIn(
            "Store",
            result,
            "an unexpected error in one fetch param must not void the others",
        )


@tagged("-at_install", "post_install", "mail_hardening_v11")
class TestControllerInputCoercionV11(HttpCase, MailCommon):
    def test_malformed_ids_are_rejected_not_crashed(self):
        """Malformed client ids must 404, never surface an uncaught exception."""
        self.authenticate("admin", "admin")
        channel = self.env["discuss.channel"]._create_channel(
            name="v11-coerce", group_id=False
        )
        self.env.flush_all()
        for post_data in (
            {"body": "x", "attachment_ids": ["abc"]},
            {"body": "x", "attachment_ids": [None]},
            {"body": "x", "partner_ids": ["x"]},
            {"body": "x", "role_ids": ["y"]},
        ):
            with self.subTest(post_data=post_data):
                with self.assertRaises(JsonRpcException) as capture:
                    self.make_jsonrpc_request(
                        "/mail/message/post",
                        {
                            "thread_model": "discuss.channel",
                            "thread_id": channel.id,
                            "post_data": post_data,
                        },
                    )
                self.assertEqual(
                    capture.exception.code,
                    404,
                    "a malformed id list must be a clean 404, not a server error",
                )

    def test_valid_post_still_works(self):
        """The coercion must not break the normal path."""
        self.authenticate("admin", "admin")
        channel = self.env["discuss.channel"]._create_channel(
            name="v11-ok", group_id=False
        )
        self.env.flush_all()
        result = self.make_jsonrpc_request(
            "/mail/message/post",
            {
                "thread_model": "discuss.channel",
                "thread_id": channel.id,
                "post_data": {"body": "hello v11"},
            },
        )
        self.assertTrue(result.get("message_id"))

    def test_read_subscription_data_rejects_bad_input(self):
        """Neither a non-integer id nor a stale res_model may raise."""
        self.authenticate("admin", "admin")
        with self.assertRaises(JsonRpcException) as capture:
            self.make_jsonrpc_request(
                "/mail/read_subscription_data", {"follower_id": "abc"}
            )
        self.assertEqual(capture.exception.code, 404)

        partner = self.env["res.partner"].create({"name": "v11 fol"})
        follower = self.env["mail.followers"].create(
            {
                "res_model": "res.partner",
                "res_id": partner.id,
                "partner_id": self.env.user.partner_id.id,
            }
        )
        follower.write({"res_model": "v11.no.such.model"})
        self.env.flush_all()
        with self.assertRaises(JsonRpcException) as capture:
            self.make_jsonrpc_request(
                "/mail/read_subscription_data", {"follower_id": follower.id}
            )
        self.assertEqual(
            capture.exception.code,
            404,
            "a follower naming a dead model must 404, not raise KeyError",
        )


@tagged("-at_install", "post_install", "mail_hardening_v11")
class TestInboxFanoutBatchingV11(MailCommon):
    """The batched prefetch must be a pure optimization: same payload, fewer
    queries. These tests pin the *semantics* first, then the cost."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["res.partner"].create({"name": "v11 fanout thread"})
        cls.inbox_users = cls.env["res.users"]
        for index in range(3):
            cls.inbox_users |= mail_new_test_user(
                cls.env,
                login=f"v11_inbox_{index}",
                groups="base.group_user",
                notification_type="inbox",
                name=f"V11 Inbox {index}",
            )
        cls.record.message_subscribe(partner_ids=cls.inbox_users.partner_id.ids)

    @contextmanager
    def _capture_inbox_payloads(self):
        """Collect the ``mail.message/inbox`` payload sent to each user."""
        captured = {}
        original = type(self.env["res.users"])._bus_send

        def capture(records, notification_type, message, /, **kwargs):
            if notification_type == "mail.message/inbox":
                for record in records:
                    captured[record.partner_id.id] = message
            return original(records, notification_type, message, **kwargs)

        type(self.env["res.users"])._bus_send = capture
        try:
            yield captured
        finally:
            type(self.env["res.users"])._bus_send = original

    @staticmethod
    def _field_of(payload, model, record_id, field):
        for entry in payload["store_data"].get(model, []):
            if entry.get("id") == record_id and field in entry:
                return entry[field]
        return None

    def test_starred_is_still_per_recipient(self):
        """Batching the starred lookup must not flatten it to a single value."""
        starrer, other = self.inbox_users[0], self.inbox_users[1]
        message = self.record.message_post(
            body="seed", message_type="comment", subtype_xmlid="mail.mt_comment"
        )
        message.with_user(starrer).toggle_message_starred()
        self.env.flush_all()
        self.assertTrue(message.with_user(starrer).starred)
        self.assertFalse(message.with_user(other).starred)

        # re-notify the very same message: notifications already exist, so drop
        # them first (the unique (message, partner) index forbids duplicates).
        self.env["mail.notification"].sudo().search(
            [("mail_message_id", "=", message.id)]
        ).unlink()
        recipients = [
            {
                "id": user.partner_id.id,
                "uid": user.id,
                "notif": "inbox",
                "active": True,
                "share": False,
                "ushare": False,
                "type": "user",
                "groups": set(),
                "lang": False,
                "name": user.name,
                "email_normalized": user.email_normalized,
                "is_follower": True,
            }
            for user in self.inbox_users
        ]
        with self._capture_inbox_payloads() as captured:
            self.record._notify_thread_by_inbox(message, recipients)

        self.assertEqual(
            self._field_of(
                captured[starrer.partner_id.id], "mail.message", message.id, "starred"
            ),
            True,
            "the recipient who starred the message must still see starred=True",
        )
        self.assertEqual(
            self._field_of(
                captured[other.partner_id.id], "mail.message", message.id, "starred"
            ),
            False,
            "a recipient who did not star it must still see starred=False",
        )

    def test_author_main_user_matches_an_unbatched_read(self):
        """The shared main_user_id must equal the per-reader value."""
        with self._capture_inbox_payloads() as captured:
            message = self.record.message_post(
                body="v11 body",
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )
        author = message.sudo().author_id
        self.assertTrue(captured, "the inbox fan-out must have sent payloads")
        for user in self.inbox_users:
            expected = author.with_user(user).sudo().main_user_id.id
            found = self._field_of(
                captured[user.partner_id.id], "res.partner", author.id, "main_user_id"
            )
            if found is not None:
                self.assertEqual(
                    found,
                    expected,
                    "batched main_user_id must equal the per-reader value",
                )

    def test_inbox_fanout_is_constant_in_recipient_count(self):
        """Query count must not grow with the number of inbox recipients."""

        def cost(user_count, tag):
            users = self.env["res.users"]
            for index in range(user_count):
                users |= mail_new_test_user(
                    self.env,
                    login=f"v11_cost_{tag}_{index}",
                    groups="base.group_user",
                    notification_type="inbox",
                    name=f"V11 Cost {tag} {index}",
                )
            record = self.env["res.partner"].create({"name": f"v11 cost {tag}"})
            record.message_subscribe(partner_ids=users.partner_id.ids)
            self.env.flush_all()
            # Warm-up post: 'res.users._get_group_ids' is @ormcache'd per user,
            # so freshly created users each cost one miss on the first message.
            # That is a fixture artifact -- in a running database those entries
            # are warm. Measure the steady state, which is what production pays.
            record.message_post(
                body="warmup", message_type="comment", subtype_xmlid="mail.mt_comment"
            )
            self.env.flush_all()
            self.env.invalidate_all()
            before = self.env.cr.sql_log_count
            record.message_post(
                body="cost", message_type="comment", subtype_xmlid="mail.mt_comment"
            )
            self.env.flush_all()
            return self.env.cr.sql_log_count - before

        few, many = cost(2, "few"), cost(20, "many")
        self.assertLess(
            many - few,
            10,
            f"inbox fan-out must be ~constant in recipients (2 -> {few} queries, "
            f"20 -> {many}); it was ~2 queries per recipient before batching",
        )


@tagged("-at_install", "post_install", "mail_hardening_v11")
class TestConfigParameterIntegersV11(MailCommon):
    """A typo in one numeric ICP must not take an unrelated subsystem down."""

    def test_helper_degrades_and_warns(self):
        icp = self.env["ir.config_parameter"]
        icp.sudo().set_param("mail.batch_size", "not-a-number")
        with self.assertLogs(
            "odoo.addons.mail.models.ir_config_parameter", level="WARNING"
        ) as capture:
            self.assertEqual(icp._get_int_param("mail.batch_size", 50), 50)
        self.assertIn("not an integer", "\n".join(capture.output))

    def test_helper_preserves_meaningful_zero(self):
        """0 means "always queue" for the force-send limit; keep it distinct
        from "unset", which must give the documented default."""
        icp = self.env["ir.config_parameter"]
        icp.sudo().set_param("mail.mail.force.send.limit", "0")
        self.assertEqual(icp._get_int_param("mail.mail.force.send.limit", 100), 0)
        icp.sudo().set_param("mail.mail.force.send.limit", False)
        self.assertEqual(icp._get_int_param("mail.mail.force.send.limit", 100), 100)

    def test_helper_accepts_int_and_str(self):
        icp = self.env["ir.config_parameter"]
        icp.sudo().set_param("mail.gateway.loop.threshold", "7")
        self.assertEqual(icp._get_int_param("mail.gateway.loop.threshold", 20), 7)
        self.assertEqual(icp._get_int_param("mail.no.such.param.at.all", 42), 42)

    @mute_logger(
        "odoo.addons.mail.models.ir_config_parameter",
        "odoo.addons.mail.models.mail_thread",
    )
    def test_broken_gateway_icp_does_not_break_loop_detection(self):
        """A non-integer loop ICP used to raise straight out of
        ``_detect_loop_sender`` -- i.e. out of ``message_process``, while
        fetchmail acks the message anyway, losing the incoming mail for good."""
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("mail.gateway.loop.minutes", "twenty")
        icp.set_param("mail.gateway.loop.threshold", "lots")
        message_dict = {
            "email_from": "sender@example.com",
            "to": "catchall@test.mycompany.com",
            "message_id": "<v11-icp@example.com>",
        }
        # must not raise, and a single mail is nowhere near any threshold
        self.assertFalse(
            self.env["mail.thread"]._detect_loop_sender(
                None, message_dict, [("res.partner", 0, {}, self.env.uid, None)]
            ),
            "a misconfigured gateway ICP must not break loop detection",
        )


@tagged("-at_install", "post_install", "mail_hardening_v11")
class TestRtcSessionIdCoercionV11(MailCommon):
    """``check_rtc_session_ids`` reaches ``_rtc_sync_sessions`` straight from
    ``/discuss/channel/ping`` and ``/mail/rtc/channel/join_call``, both
    ``auth="public"``. A bare ``int()`` there surfaced ValueError/TypeError as a
    server error to any channel member -- including a guest member of a public
    channel."""

    def test_malformed_session_ids_are_skipped(self):
        channel = self.env["discuss.channel"]._create_channel(
            name="v11-rtc", group_id=False
        )
        member = channel._find_or_create_member_for_self()
        self.assertTrue(member)
        # must not raise on any of these
        for check_ids in ([], ["abc"], [None], [{}], ["7", 8], [1.0]):
            with self.subTest(check_rtc_session_ids=check_ids):
                current, outdated = member._rtc_sync_sessions(
                    check_rtc_session_ids=check_ids
                )
                self.assertIsNotNone(current)
                self.assertIsNotNone(outdated)

    def test_numeric_strings_still_resolve(self):
        """Skipping garbage must not also drop usable numeric strings."""
        channel = self.env["discuss.channel"]._create_channel(
            name="v11-rtc-2", group_id=False
        )
        member = channel._find_or_create_member_for_self()
        session = self.env["discuss.channel.rtc.session"].create(
            {"channel_member_id": member.id}
        )
        self.env.flush_all()
        # a live session passed as a string is a *current* session, not outdated
        __, outdated = member._rtc_sync_sessions(
            check_rtc_session_ids=[str(session.id), "abc"]
        )
        self.assertNotIn(
            session.id,
            outdated.ids,
            "a numeric string must still resolve to its session",
        )
