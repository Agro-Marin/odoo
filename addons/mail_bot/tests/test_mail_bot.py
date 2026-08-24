import json
from unittest.mock import patch

from markupsafe import Markup

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.mail_bot.tests.common import MailBotCommon


@tagged("odoobot")
class TestBotSilence(MailBotCommon):

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_disabled_state_silences_the_bot(self):
        """"Disabled" means disabled.

        The state only ever gated `_init_odoobot`; `_get_answer` never read it,
        so a user an administrator had explicitly switched off kept being
        answered for ever.
        """
        self._set_state("disabled")
        self.assertFalse(self._say("hello there"))
        self.assertFalse(self._say("can you help me"))
        self.assertFalse(self._say("start the tour"))
        self.assertFalse(self._say("tagada 😊"))

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_disabled_state_never_reaches_the_banter(self):
        """`disabled` used to be one of only three states reaching random banter.

        It is not in `_RESTARTABLE_STATES`, so "start the tour" fell through to
        `random.choice` -- the switched-off user got *more* undirected chatter
        than an idle one, and could not restart the tour either.
        """
        self._set_state("disabled")
        with patch("random.choice", side_effect=AssertionError("banter branch reached")):
            self.assertFalse(self._say("banana"))

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_bot_is_silent_outside_a_chat_with_odoobot(self):
        group = self.env["discuss.channel"].with_user(self.bot_user)._create_channel(
            name="no bot here", group_id=None)
        group.add_members(partner_ids=self.bot_user.partner_id.ids)
        self._set_state("idle")
        self.assertFalse(self._say("hello", channel=group))

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_bot_does_not_answer_its_own_message(self):
        self._set_state("idle")
        answers = self._say("hello")
        self.assertEqual(len(answers), 1, "odoobot answered its own answer")


@tagged("odoobot")
class TestStepHints(MailBotCommon):

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_step_hint_is_repeated_after_every_mistake(self):
        """The hint must survive the first failure.

        `_is_help_requested` used to be OR-ed with `odoobot_failed`, so once the
        user had got it wrong once every later message read as a help request
        and got generic documentation links instead of the step's own hint --
        the guidance disappeared exactly when the user was struggling.
        """
        self._set_state("onboarding_emoji")
        first = self._say_one("nope")
        self.assertIn("send an emoji", first)
        for attempt in ("nope again", "still no", "not this either"):
            again = self._say_one(attempt)
            self.assertIn("send an emoji", again,
                          f"hint lost after a previous mistake ({attempt!r})")

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_repeated_mistakes_add_documentation_to_the_hint(self):
        """A struggling user gets the hint *and* the links, never the links alone."""
        self._set_state("onboarding_emoji")
        first = self._say_one("nope")
        self.assertIn("send an emoji", first)
        self.assertNotIn("documentation", first, "the first hint stays uncluttered")
        second = self._say_one("nope again")
        self.assertIn("send an emoji", second, "the step hint must survive")
        self.assertIn("documentation", second, "a repeated mistake earns the links")

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_explicit_help_still_wins(self):
        """Asking for help explicitly still gets the documentation links."""
        self._set_state("onboarding_emoji")
        self.assertIn("documentation", self._say_one("help"))

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_failure_flag_tracks_the_step(self):
        self._set_state("onboarding_emoji")
        self._say("nope")
        self.assertTrue(self.bot_user.odoobot_failed)
        self._say("here 😊")
        self.assertFalse(self.bot_user.odoobot_failed)
        self.assertEqual(self.bot_user.odoobot_state, "onboarding_command")


@tagged("odoobot")
class TestBodyIsHtml(MailBotCommon):
    """The matching rules see what the user typed, not the markup around it."""

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_exact_match_rules_work_on_a_real_client_body(self):
        """A Discuss client sends `<p>I love you</p>`, never a bare string.

        The exact-match rules compared against the raw body, so they could only
        fire for a caller passing an unwrapped string -- i.e. a test. For a real
        user this branch was dead.
        """
        self._set_state("idle")
        self.assertIn("too human for me", self._say_one(Markup("<p>I love you</p>")))

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_swearing_is_answered_from_any_state(self):
        """The one branch that does not care which state the user is in."""
        for state in ("idle", "onboarding_emoji", "onboarding_ping"):
            self._set_state(state)
            self.assertIn("I have feelings",
                          self._say_one(Markup("<p>Go fuck yourself</p>")),
                          f"the swear branch did not fire in {state}")

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_emoji_is_found_inside_markup(self):
        self._set_state("onboarding_emoji")
        self.assertIn("special commands", self._say_one(Markup("<p>tagada 😊</p>")))
        self.assertEqual(self.bot_user.odoobot_state, "onboarding_command")


@tagged("odoobot")
class TestHelpPredicate(MailBotCommon):

    def test_is_help_requested_is_a_pure_predicate(self):
        """It answers a question about the body and nothing else."""
        bot = self.env["mail.bot"].with_user(self.bot_user)
        self.bot_user.sudo().odoobot_failed = True
        self.assertFalse(bot._is_help_requested("banana"),
                         "a previous failure is not a help request")
        for body in ("help", "help me", "i need help please", "what now?"):
            self.assertTrue(bot._is_help_requested(body), body)
        for body in ("whelped", "what is the shelp", "helpful", "banana"):
            self.assertFalse(bot._is_help_requested(body),
                             f"{body!r} is not a help request")


@tagged("odoobot")
class TestNotificationOrder(MailBotCommon):

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_answer_is_notified_after_the_question(self):
        """The bus must carry the question before the answer.

        Replying from `_message_post_after_hook` -- which runs before
        `_notify_thread` -- put the answer on the bus first, and `thread.messages`
        is unsorted on the client, so a session without an optimistic copy of the
        user's own message rendered the answer above the question.
        """
        self._set_state("idle")
        with self.mock_bus():
            question = self.bot_channel.with_user(self.bot_user).message_post(
                body="hello", message_type="comment", subtype_xmlid="mail.mt_comment")
        broadcast = []
        for notification in self._new_bus_notifs:
            payload = json.loads(notification.message)
            if payload.get("type") != "discuss.channel/new_message":
                continue
            data = payload.get("payload", {}).get("data", {})
            broadcast += [record["id"] for record in data.get("mail.message", [])]
        answer = self.env["mail.message"].search([
            ("model", "=", "discuss.channel"),
            ("res_id", "=", self.bot_channel.id),
            ("author_id", "=", self.odoobot.id),
        ], order="id desc", limit=1)
        self.assertTrue(answer, "odoobot did not answer")
        self.assertEqual(
            [message_id for message_id in broadcast if message_id in (question.id, answer.id)],
            [question.id, answer.id],
            "odoobot's answer reached the bus before the message it answers",
        )


@tagged("odoobot")
class TestBatchPost(MailBotCommon):

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_batch_post_does_not_trigger_the_bot(self):
        """`_message_post_batch` posts notifications, which the bot ignores.

        This is what makes replying from `message_post` rather than from
        `_message_post_after_hook` safe: the batch path cannot produce an answer
        in the first place.
        """
        self._set_state("idle")
        before = self.env["mail.message"].search_count([
            ("model", "=", "discuss.channel"), ("res_id", "=", self.bot_channel.id)])
        self.bot_channel.with_user(self.bot_user)._message_post_batch(
            {self.bot_channel.id: "batched body"})
        after = self.env["mail.message"].search([
            ("model", "=", "discuss.channel"), ("res_id", "=", self.bot_channel.id)],
            order="id")
        self.assertEqual(len(after) - before, 1, "the bot answered a batched notification")
        self.assertNotEqual(after[-1].author_id, self.odoobot)
