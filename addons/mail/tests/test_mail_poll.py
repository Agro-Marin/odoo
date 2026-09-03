from pprint import pformat

from odoo.tests import HttpCase, JsonRpcException, new_test_user, tagged


@tagged("post_install", "-at_install", "mail_poll")
class TestMailPoll(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.internal = new_test_user(cls.env, "internal", groups="base.group_user")

    def _create_poll(self, **overrides):
        values = {
            "duration": 1,
            "option_labels": ["Burger", "Pizza", "Tacos"],
            "question": "What is your favorite food?",
            "thread_id": self.env["discuss.channel"].create({"name": "General"}).id,
            "thread_model": "discuss.channel",
        }
        values.update(overrides)
        poll_id = self.call_jsonrpc("/mail/poll/create", values)
        return self.env["mail.poll"].browse(poll_id)

    def test_only_one_option_allowed_on_single_option_polls(self):
        self.authenticate(self.internal.login, self.internal.login)
        poll = self._create_poll()
        with (
            self.assertRaises(JsonRpcException) as error_catcher,
            self.assertLogs("odoo.http.application", level="WARNING") as log_catcher,
        ):
            self.call_jsonrpc(
                "/mail/poll/vote",
                {"poll_id": poll.id, "option_ids": poll.option_ids.ids},
            )
        self.assertEqual(
            str(error_catcher.exception), "odoo.exceptions.ValidationError"
        )
        self.assertIn(
            "WARNING:odoo.http.application:Cannot vote on poll "
            '"What is your favorite food?": only one vote is allowed per user.',
            log_catcher.output,
        )
        self.call_jsonrpc(
            "/mail/poll/vote",
            {"poll_id": poll.id, "option_ids": poll.option_ids[0].ids},
        )
        self.assertIn(self.internal, poll.option_ids[0].vote_ids.user_id)

    def test_multiple_options_allowed_on_multi_option_polls(self):
        self.authenticate(self.internal.login, self.internal.login)
        poll = self._create_poll(allow_multiple_options=True)
        self.call_jsonrpc(
            "/mail/poll/vote", {"poll_id": poll.id, "option_ids": poll.option_ids.ids}
        )
        for option in poll.option_ids:
            self.assertIn(self.internal, option.vote_ids.user_id)

    def test_vote_percentage_computation(self):
        self.authenticate(self.internal.login, self.internal.login)
        poll = self._create_poll(allow_multiple_options=True)
        cases = [
            [{"option": poll.option_ids[0], "votes": 1, "expected_percentage": 100}],
            [
                {"option": poll.option_ids[0], "votes": 1, "expected_percentage": 50},
                {"option": poll.option_ids[1], "votes": 1, "expected_percentage": 50},
            ],
            # remainder skipped so as not to skew the results
            [
                {"option": poll.option_ids[0], "votes": 1, "expected_percentage": 33},
                {"option": poll.option_ids[1], "votes": 1, "expected_percentage": 33},
                {"option": poll.option_ids[2], "votes": 1, "expected_percentage": 33},
            ],
            [
                {"option": poll.option_ids[0], "votes": 0, "expected_percentage": 0},
                {"option": poll.option_ids[1], "votes": 0, "expected_percentage": 0},
                {"option": poll.option_ids[2], "votes": 0, "expected_percentage": 0},
            ],
            [
                {"option": poll.option_ids[0], "votes": 2, "expected_percentage": 67},
                {"option": poll.option_ids[1], "votes": 1, "expected_percentage": 33},
            ],
            [
                {"option": poll.option_ids[0], "votes": 3, "expected_percentage": 50},
                {"option": poll.option_ids[1], "votes": 2, "expected_percentage": 33},
                {"option": poll.option_ids[2], "votes": 1, "expected_percentage": 17},
            ],
        ]
        max_votes = max(sum(a["votes"] for a in case) for case in cases)
        users = self.env["res.users"].browse(
            [
                new_test_user(self.env, f"user{i}", groups="base.group_user").id
                for i in range(1, max_votes + 1)
            ]
        )
        for case in cases:
            with self.subTest(pformat(case)):
                poll.option_ids.vote_ids.unlink()
                self.env["mail.poll.vote"].create(
                    [
                        {"option_id": option_data["option"].id, "user_id": user.id}
                        for option_data in case
                        for user in users[: option_data["votes"]]
                    ]
                )
                for option_data in case:
                    self.assertEqual(
                        option_data["option"].vote_percentage,
                        option_data["expected_percentage"],
                    )

    def test_cannot_vote_on_a_closed_poll(self):
        self.authenticate(self.internal.login, self.internal.login)
        poll = self._create_poll()
        poll.sudo()._end_and_notify()
        self.assertTrue(poll.end_message_id)
        with self.assertRaises(JsonRpcException):
            self.call_jsonrpc(
                "/mail/poll/vote",
                {"poll_id": poll.id, "option_ids": poll.option_ids[0].ids},
            )
        self.assertFalse(poll.option_ids.vote_ids)

    def test_expired_polls_are_ended_once(self):
        """The cron must not re-post a closing message on a poll it already
        closed: `poll_end_dt` stays in the past forever, so an unfiltered search
        would announce the same poll again on every run."""
        self.authenticate(self.internal.login, self.internal.login)
        poll = self._create_poll(duration=-1)
        channel = self.env["discuss.channel"].browse(poll.start_message_id.res_id)
        self.env["mail.poll"].sudo()._end_expired_polls()
        end_message = poll.end_message_id
        self.assertTrue(end_message)
        message_count = len(channel.message_ids)
        self.env["mail.poll"].sudo()._end_expired_polls()
        self.assertEqual(poll.end_message_id, end_message)
        self.assertEqual(len(channel.message_ids), message_count)

    def test_deleting_a_poll_empties_its_message(self):
        """Deleting the poll takes its options and votes with it and leaves the
        message it was posted in empty, which is what renders as "This message
        has been removed"."""
        self.authenticate(self.internal.login, self.internal.login)
        poll = self._create_poll()
        start_message = poll.start_message_id
        options = poll.option_ids
        self.assertFalse(start_message._is_empty())
        self.call_jsonrpc("/mail/poll/delete", {"poll_id": poll.id})
        self.assertFalse(poll.exists())
        self.assertFalse(options.exists())
        self.assertTrue(start_message.exists())
        self.assertTrue(start_message._is_empty())

    def test_poll_creation_is_refused_outside_a_channel(self):
        """Polls are a Discuss feature. A bare `mixin.mail.thread` record is not
        a `mixin.bus.listener` here, so it has no bus channel to broadcast the
        result on: the route refuses it instead of raising deep in `Store`."""
        self.authenticate(self.internal.login, self.internal.login)
        partner = self.env["res.partner"].create({"name": "Poll Target"})
        self.assertIsNone(
            self.call_jsonrpc(
                "/mail/poll/create",
                {
                    "duration": 1,
                    "option_labels": ["Yes", "No"],
                    "question": "Really?",
                    "thread_id": partner.id,
                    "thread_model": "res.partner",
                },
            )
        )
        self.assertFalse(self.env["mail.poll"].search([]))

    def test_poll_ui(self):
        channel = self.env["discuss.channel"].create({"name": "General"})
        channel.add_members(partner_ids=self.internal.partner_id.ids)
        self.start_tour(
            f"/odoo/discuss?active_id={channel.id}",
            "mail_poll_tour",
            login=self.internal.login,
        )
