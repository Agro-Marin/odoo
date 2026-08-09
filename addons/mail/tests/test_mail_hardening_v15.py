"""Regression tests for the fifteenth mail hardening audit.

Each test pins a defect reproduced end to end before being fixed, so a refactor
cannot silently reintroduce it.
"""

from unittest.mock import patch

from odoo.tests import HttpCase, JsonRpcException, tagged
from odoo.tools import mute_logger

from odoo.addons.mail.tests.common import MailCommon
from odoo.addons.mail.tools.discuss import Store


@tagged("mail_followers", "post_install", "-at_install")
class TestUnfollowLinkIsPerRecipientV15(MailCommon):
    """The Unfollow link must be decided per recipient, not per mail.

    A notification group is split into mails of at most ``mail.batch_size``
    partners, and a group mixes record followers with partners reached only
    through ``partner_ids`` (a mention, an explicit recipient). All of them share
    one ``mail.mail`` and therefore one ``body_html``; the Unfollow block is
    meant to be stripped per recipient in ``_personalize_outgoing_body``.

    That method used to gate on ``doc_to_followers.get((model, res_id))``, which
    is the *list of this mail's recipients that follow the record* -- truthy as
    soon as a single one does. Every co-recipient of one follower was therefore
    offered an Unfollow link for a document they do not follow.

    The existing coverage in ``test_mail_followers`` subscribes and unsubscribes
    all of its partners together, so the mixed mail this exercises never arose.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # res.partner is a mail.thread, so this runs without test_mail.
        cls.document = cls.env["res.partner"].create({"name": "V15 Document"})
        # Two *internal* users: they land in the same "user" notification group
        # (so they share one mail), and ``not partner_share`` lets them reach the
        # unfollow branch without the model opting in via
        # ``_partner_unfollow_enabled``.
        cls.user_follower, cls.user_mentioned = cls.env["res.users"].create(
            [
                {
                    "email": "v15.follower@example.com",
                    "group_ids": [(4, cls.env.ref("base.group_user").id)],
                    "login": "v15_follower",
                    "name": "V15 Follower",
                    "notification_type": "email",
                },
                {
                    "email": "v15.mentioned@example.com",
                    "group_ids": [(4, cls.env.ref("base.group_user").id)],
                    "login": "v15_mentioned",
                    "name": "V15 Mentioned",
                    "notification_type": "email",
                },
            ]
        )
        cls.partner_follower = cls.user_follower.partner_id
        cls.partner_mentioned = cls.user_mentioned.partner_id

    def test_unfollow_link_only_for_the_recipient_that_follows(self):
        """One mail, two internal recipients, only one of them a follower."""
        self.document._message_subscribe(partner_ids=self.partner_follower.ids)
        self.assertIn(self.partner_follower, self.document.message_partner_ids)
        self.assertNotIn(self.partner_mentioned, self.document.message_partner_ids)

        follower_url, mentioned_url = self._message_post_and_get_unfollow_urls(
            self.document, self.partner_follower + self.partner_mentioned
        )

        self.assertTrue(
            follower_url,
            "a recipient that follows the record must still get the unfollow link",
        )
        self.assertFalse(
            mentioned_url,
            "a recipient that does not follow the record must not be offered to "
            "unfollow it, even when sharing a mail with a follower",
        )

    def test_unfollow_link_per_recipient_under_production_footer_context(self):
        """Same leak, reached the way production reaches it.

        ``_message_post_and_get_unfollow_urls`` forces the footer
        (``email_notification_force_footer``), which is a test-only key. The
        footer is off by default (``email_notification_allow_footer`` defaults
        to False in ``mail.render.mixin``), so this pins the leak under the key
        real callers set instead: ``sale.order``, ``purchase.order`` and
        ``account.move.send`` all post with
        ``email_notification_allow_footer=True``.
        """
        self.document._message_subscribe(partner_ids=self.partner_follower.ids)
        with self.mock_mail_gateway():
            self.document.with_user(self.env.ref("base.user_admin")).with_context(
                email_notification_allow_footer=True,
            ).message_post(
                body="production body",
                partner_ids=(self.partner_follower + self.partner_mentioned).ids,
                subtype_id=self.env.ref("mail.mt_comment").id,
                message_type="comment",
            )
        bodies = {
            email_to: mail["body"]
            for mail in self._mails
            for email_to in mail["email_to"]
        }
        follower_body = next(
            body for to, body in bodies.items() if "v15.follower" in to
        )
        mentioned_body = next(
            body for to, body in bodies.items() if "v15.mentioned" in to
        )
        self.assertIn(
            "/mail/unfollow",
            follower_body,
            "control: the footer really is rendered under this context",
        )
        self.assertNotIn(
            "/mail/unfollow",
            mentioned_body,
            "the non-follower sharing that mail must not be offered to unfollow",
        )

    def test_unfollow_link_absent_when_no_recipient_follows(self):
        """Control: the mail carries no unfollow link at all in that case."""
        self.assertNotIn(self.partner_follower, self.document.message_partner_ids)
        self.assertNotIn(self.partner_mentioned, self.document.message_partner_ids)

        urls = self._message_post_and_get_unfollow_urls(
            self.document, self.partner_follower + self.partner_mentioned
        )

        self.assertEqual(urls, [False, False])


@tagged("mail_store", "post_install", "-at_install")
class TestThreadToStoreIsPerRecordV15(MailCommon):
    """``_thread_to_store`` must answer per thread, not per recordset.

    The method loops over ``self``, but ``canPostOnReadonly`` read the
    permission map with ``.get(self)`` -- the *whole* recordset as the key. The
    map is keyed by record, so the lookup only ever hit while ``self`` happened
    to be a singleton, which every current caller is; on a batch it missed every
    key and reported ``False`` for all of them.

    Pinned by comparing a batch against the single-record answer, so the bug
    cannot come back the day a caller serialises more than one thread at once.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # res.partner is a mail.thread, so this runs without test_mail.
        cls.threads = cls.env["res.partner"].create(
            [{"name": "V15 Thread A"}, {"name": "V15 Thread B"}]
        )

    def _can_post_on_readonly(self, records):
        """{record id: canPostOnReadonly} as the chatter would receive it."""
        store = Store()
        store.add(records, [], as_thread=True, request_list=[])
        return {
            row["id"]: row["canPostOnReadonly"]
            for row in store.get_result().get("mail.thread", [])
        }

    def test_can_post_on_readonly_matches_between_single_and_batch(self):
        """A readonly-postable model must say so for every thread of a batch."""
        # 'read' is what makes the flag True at all; the default 'write' answers
        # False for both shapes and so cannot tell them apart.
        with patch.object(
            type(self.env["res.partner"]), "_mail_post_access", "read", create=True
        ):
            singles = {}
            for thread in self.threads:
                singles.update(self._can_post_on_readonly(thread))
            batch = self._can_post_on_readonly(self.threads)

        self.assertEqual(
            singles,
            dict.fromkeys(self.threads.ids, True),
            "control: served one at a time, each thread is postable on readonly",
        )
        self.assertEqual(
            batch,
            singles,
            "a batched thread payload must carry the same per-record answer as "
            "the single-record one",
        )


@tagged("mail_controller", "post_install", "-at_install")
class TestOperationMapWithoutPermissionV15(MailCommon):
    """A document carrying *no* permission must read as denied, not raise.

    ``_mail_get_operation_for_mail_message_operation`` returns a map keyed by
    record, and omitting a record is the documented way to grant it nothing --
    ``_mail_group_by_operation_for_mail_message_operation`` discards those
    explicitly, and ``mail.test.access.custo`` (test_mail) implements exactly
    that shape: ``dict.fromkeys(self.filtered(lambda r: not r.is_locked), 'read')``.

    Both readers indexed the map with ``[thread_su]``, so an omitted record
    raised ``KeyError`` instead of taking the ``if not access_mode`` branch
    right below. Reproduced over HTTP before the fix: posting to a locked
    record as a non-admin answered ``builtins.KeyError:
    mail.test.access.custo(1,)``.

    Pinned here with a patched override rather than the test_mail model, so
    ``addons/mail`` keeps testing without ``test_mail`` installed.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.document = cls.env["res.partner"].create({"name": "V15 No Permission"})
        cls.message = cls.document.message_post(
            body="v15 body",
            message_type="comment",
            subtype_id=cls.env.ref("mail.mt_comment").id,
        )

    def test_absent_record_in_operation_map_denies_instead_of_raising(self):
        """An override that omits the record must deny, not KeyError."""
        for mode in ("read", "write", "unlink"):
            with self.subTest(mode=mode):
                with patch.object(
                    type(self.env["res.partner"]),
                    "_mail_get_operation_for_mail_message_operation",
                    lambda self, message_operation: {},
                ):
                    # The employee has no access of their own on this message,
                    # so resolution falls through to the document permission map.
                    granted = (
                        self.env["mail.message"]
                        .with_user(self.user_employee)
                        ._get_with_access(self.message.id, mode=mode)
                    )
                self.assertFalse(
                    granted,
                    "a document that grants no permission must deny access, and "
                    "must not raise out of the access check",
                )


@tagged("mail_controller", "post_install", "-at_install")
class TestNonThreadModelIsDeniedV15(HttpCase, MailCommon):
    """A live model that is not a thread must be refused like an unknown one.

    The chatter routes guarded their caller-supplied model name with
    ``thread_model not in request.env``, which rules out the *uninstalled* model
    but not the installed *non-thread* one -- ``res.currency``, or ``res.users``,
    which delegates to ``res.partner`` through ``_inherits`` and so never
    inherited ``mail.thread``. The ``mail.thread`` methods these routes then call
    raised ``AttributeError``, i.e. an unhandled traceback in the log and the
    internal message echoed back to the caller, where the module's own
    ``mail.message._is_thread_model`` had already settled that the answer is 404.

    The invariant pinned here is the one that cannot rot: a live non-thread model
    must be answered exactly like a model that does not exist at all.
    """

    def _rpc_error(self, route, params):
        """The error message a route answers with, or None when it succeeds."""
        with mute_logger("odoo.http"):
            try:
                self.make_jsonrpc_request(route=route, params=params)
            except JsonRpcException as exc:
                return str(exc)
        return None

    def test_live_non_thread_model_is_answered_like_an_unknown_model(self):
        self.authenticate("admin", "admin")
        for route, key_model, key_id in [
            ("/mail/thread/messages", "thread_model", "thread_id"),
            ("/mail/thread/subscribe", "res_model", "res_id"),
            ("/mail/thread/unsubscribe", "res_model", "res_id"),
        ]:
            baseline = self._rpc_error(
                route, {key_model: "no.such.model.at.all", key_id: 1, "partner_ids": []}
            )
            self.assertTrue(baseline, "an unknown model must be refused")
            for model in ("res.currency", "res.users"):
                with self.subTest(route=route, model=model):
                    self.assertFalse(
                        isinstance(self.env[model], self.env.registry["mail.thread"]),
                        "control: this model must really not be a thread",
                    )
                    error = self._rpc_error(
                        route, {key_model: model, key_id: 1, "partner_ids": []}
                    )
                    self.assertEqual(
                        error,
                        baseline,
                        "a live non-thread model must be refused exactly like an "
                        "unknown one, not leak an AttributeError",
                    )
                    self.assertNotIn("has no attribute", error or "")


@tagged("mail_notify", "post_install", "-at_install")
class TestOutgoingEmailToDedupV15(MailCommon):
    """``outgoing_email_to`` must not re-email an address already covered.

    The email-only recipients built from that field were appended to
    ``recipients_data`` unconditionally, after the loop that filters the
    partner-based ones. So an address that is *also* a partner recipient landed
    twice, once as the partner and once as a bare address, and each entry gets
    its own ``mail.mail`` -- two messages in the same mailbox. The same held for
    an address repeated inside the field, and for one already reached as a To/Cc
    of the incoming gateway mail (which the partner branch does skip).

    An unparseable address is dropped by ``email_split_tuples`` before it ever
    reaches here, so the test feeds one only to pin that it stays dropped.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.document = cls.env["res.partner"].create({"name": "V15 OET Document"})
        cls.customer = cls.env["res.partner"].create(
            {"name": "V15 OET Customer", "email": "dup@example.com"}
        )

    def _email_recipients(self, **msg_vals):
        rdata = self.document._notify_get_recipients(
            self.env["mail.message"],
            {
                "message_type": "comment",
                "partner_ids": self.customer.ids,
                "subtype_id": self.env.ref("mail.mt_comment").id,
                **msg_vals,
            },
        )
        return [r["email_normalized"] for r in rdata if r["notif"] == "email"]

    def test_outgoing_email_to_is_deduped_and_sanitised(self):
        emails = self._email_recipients(
            # the customer's own address (differently cased), a repeat, a malformed one
            outgoing_email_to=(
                "DUP@Example.com, other@example.com, other@example.com, not-an-email"
            ),
        )
        self.assertEqual(
            sorted(emails),
            ["dup@example.com", "other@example.com"],
            "each mailbox must be reached exactly once, and an unparseable "
            "address must not become a recipient at all",
        )

    def test_outgoing_email_to_respects_the_incoming_recipients(self):
        """An address already reached as a To/Cc of the incoming mail is skipped."""
        emails = self._email_recipients(
            incoming_email_to="other@example.com",
            outgoing_email_to="other@example.com, fresh@example.com",
        )
        self.assertNotIn(
            "other@example.com",
            emails,
            "the incoming mail already reached that mailbox",
        )
        self.assertIn("fresh@example.com", emails)

    def test_outgoing_email_to_still_reaches_a_new_address(self):
        """Control: an address covered by nothing else is still notified."""
        self.assertIn(
            "brand.new@example.com",
            self._email_recipients(outgoing_email_to="brand.new@example.com"),
        )


@tagged("mail_store", "post_install", "-at_install")
class TestFollowersPayloadQueriesV15(MailCommon):
    """The chatter's follower payload must not count what it just fetched.

    ``_thread_to_store``'s "followers" branch issued two ``search_count`` calls
    over ``mail_followers`` right next to the two searches that fetch the first
    page of the very same rows. A page that comes back shorter than the limit is
    already the whole set, so both totals are derivable -- and every record with
    fewer than ``_FOLLOWER_PAGE_LIMIT`` followers, which is essentially all of
    them, takes that branch.

    Two things are pinned: the totals stay exactly what the ``search_count``
    queries answered (including the page-full fallback, where deriving would be
    wrong), and the payload does not regain a per-record count query.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.subtype_comment_id = cls.env.ref("mail.mt_comment").id

    def _make(self, name, follower_count, with_self=False):
        document = self.env["res.partner"].create({"name": name})
        followers = self.env["res.partner"].create(
            [
                {"email": f"{name}{idx}@example.com", "name": f"{name} {idx}"}
                for idx in range(follower_count)
            ]
        )
        if with_self:
            followers |= self.env.user.partner_id
        document._message_subscribe(partner_ids=followers.ids)
        self.env.flush_all()
        return document

    def _counts_by_query(self, document):
        """What the two search_count calls this replaced would have answered."""
        Followers = self.env["mail.followers"]
        base = [("res_id", "=", document.id), ("res_model", "=", document._name)]
        return (
            Followers.search_count(base),
            Followers.search_count(
                base
                + [
                    ("partner_id", "!=", self.env.user.partner_id.id),
                    ("subtype_ids", "=", self.subtype_comment_id),
                    ("partner_id.active", "=", True),
                ]
            ),
        )

    def _counts_by_payload(self, document):
        store = Store()
        store.add(document, [], as_thread=True, request_list=["followers"])
        row = next(
            r for r in store.get_result()["mail.thread"] if r["id"] == document.id
        )
        return row["followersCount"], row["recipientsCount"]

    def test_counts_match_the_queries_they_replaced(self):
        page_limit = self.env["res.partner"]._FOLLOWER_PAGE_LIMIT
        for label, document in [
            ("no follower", self._make("v15q0", 0)),
            ("self only", self._make("v15qs", 0, with_self=True)),
            ("others only", self._make("v15qo", 4)),
            ("self and others", self._make("v15qb", 4, with_self=True)),
        ]:
            with self.subTest(case=label):
                self.assertEqual(
                    self._counts_by_payload(document),
                    self._counts_by_query(document),
                )
        # Around a page boundary the short-page shortcut must hand back to the
        # count query; shrink the page rather than create 100+ partners.
        document = self._make("v15qlim", 6)
        with patch.object(type(self.env["res.partner"]), "_FOLLOWER_PAGE_LIMIT", 5):
            for follower_count in (4, 5, 6):
                with self.subTest(case=f"page boundary, {follower_count} followers"):
                    trimmed = self._make(f"v15qb{follower_count}", follower_count)
                    self.assertEqual(
                        self._counts_by_payload(trimmed),
                        self._counts_by_query(trimmed),
                    )
        self.assertEqual(page_limit, self.env["res.partner"]._FOLLOWER_PAGE_LIMIT)

    def test_payload_cost_is_flat_in_follower_count(self):
        """No per-follower query, and no count query on the common short page."""
        counts = []
        for follower_count in (2, 20, 60):
            document = self._make(f"v15flat{follower_count}", follower_count)
            self._counts_by_payload(document)  # warm anything not per-follower
            self.env.invalidate_all()
            before = self.env.cr.sql_log_count
            self._counts_by_payload(document)
            counts.append(self.env.cr.sql_log_count - before)
        self.assertEqual(
            len(set(counts)),
            1,
            f"query count must not grow with the follower count, got {counts}",
        )
