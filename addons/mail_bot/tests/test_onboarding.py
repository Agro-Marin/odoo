from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.mail_bot.tests.common import MailBotCommon


@tagged("odoobot", "post_install", "-at_install")
class TestOnboardingFlow(MailBotCommon):

    def _attachment(self):
        return self.env["ir.attachment"].with_user(self.bot_user).create({
            "datas": "bWlncmF0aW9uIHRlc3Q=",
            "name": "picture_of_your_dog.doc",
            "res_model": "mail.compose.message",
        })

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_full_tour_walks_every_step(self):
        """Drive the tour end to end, including the two-message finish.

        The pre-existing suite stopped after the attachment step, so the branch
        that returns a *list* of answers -- and the canned-response cleanup it
        performs -- was never exercised.
        """
        self.assertEqual(self.bot_user.odoobot_state, "onboarding_emoji")

        self.assertIn("special commands", self._say_one("tagada 😊"))
        self.assertEqual(self.bot_user.odoobot_state, "onboarding_command")

        self.bot_channel.with_user(self.bot_user).execute_command_help()
        self.assertEqual(self.bot_user.odoobot_state, "onboarding_ping")

        self.assertIn("sending an attachment",
                      self._say_one("", partner_ids=[self.odoobot.id]))
        self.assertEqual(self.bot_user.odoobot_state, "onboarding_attachment")

        self.assertIn("canned responses",
                      self._say_one("", attachment_ids=[self._attachment().id]))
        self.assertEqual(self.bot_user.odoobot_state, "onboarding_canned")

        answers = self._say("thanks", context={"canned_response_ids": [1]})
        self.assertEqual(len(answers), 2, "the closing step answers twice")
        self.assertIn("customize", answers[0])
        self.assertIn("end of this overview", answers[1])
        self.assertEqual(self.bot_user.odoobot_state, "idle")

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_start_the_tour_restarts_from_idle(self):
        self._set_state("idle")
        self.assertIn("send me an emoji", self._say_one("start the tour"))
        self.assertEqual(self.bot_user.odoobot_state, "onboarding_emoji")


@tagged("odoobot", "post_install", "-at_install")
class TestCannedResponseCleanup(MailBotCommon):

    def _reach_canned_step(self):
        self._set_state("onboarding_attachment")
        attachment = self.env["ir.attachment"].with_user(self.bot_user).create({
            "datas": "bWln", "name": "dog.doc", "res_model": "mail.compose.message"})
        self._say("", attachment_ids=[attachment.id])
        self.assertEqual(self.bot_user.odoobot_state, "onboarding_canned")

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_cleanup_keeps_the_users_own_canned_response(self):
        """The tour must delete its own record and nothing else.

        The cleanup matched `source = _("Thanks")` for the whole user, so a
        canned response the user had abbreviated "Thanks" was silently deleted
        along with the throw-away one. `start the tour` makes that reachable at
        any point in an established account's life.
        """
        mine = self.env["mail.canned.response"].with_user(self.bot_user).create({
            "source": "Thanks", "substitution": "MY OWN IMPORTANT TEXT"})
        self._reach_canned_step()
        self._say("thanks", context={"canned_response_ids": [1]})
        self.assertTrue(mine.exists(), "the tour deleted the user's own canned response")
        self.assertEqual(mine.substitution, "MY OWN IMPORTANT TEXT")
        self.assertFalse(self.bot_user.odoobot_canned_response_id,
                         "the throw-away canned response was not cleaned up")

    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_cleanup_survives_a_language_change(self):
        """Cleanup is by identity, not by a re-translated literal.

        Created as "Gracias" under es_ES and searched for as "Merci" under
        fr_FR, the throw-away record used to be stranded for ever -- the state
        still advanced to idle, so nothing ever revisited it.
        """
        self.env["res.lang"]._activate_lang("es_ES")
        self.env["res.lang"]._activate_lang("fr_FR")
        self.bot_user.sudo().lang = "es_ES"
        self._reach_canned_step()
        throwaway = self.bot_user.odoobot_canned_response_id
        self.assertTrue(throwaway, "no throw-away canned response was recorded")

        self.bot_user.sudo().lang = "fr_FR"
        self.env.registry.clear_cache()
        self._say("merci", context={"canned_response_ids": [1]})
        self.assertEqual(self.bot_user.odoobot_state, "idle")
        self.assertFalse(throwaway.exists(),
                         "the throw-away canned response was orphaned by the language change")
