from odoo import tests
from odoo.addons.base.tests.common import HttpCaseWithUserDemo


@tests.tagged("post_install", "-at_install")
class TestLivechatChatbotFormUI(HttpCaseWithUserDemo):
    def test_chatbot_steps_sequence_ui(self):
        self.start_tour(
            '/odoo',
            'im_livechat_chatbot_steps_sequence_tour',
            login='admin',
        )

        chatbot_script = self.env['chatbot.script'].search([('title', '=', 'Test Chatbot Sequence')])

        self.assertEqual(len(chatbot_script.script_step_ids), 3)

        self.assertEqual(chatbot_script.script_step_ids[0].message, "<p>Step 1</p>")
        self.assertEqual(chatbot_script.script_step_ids[0].sequence, 0)
        self.assertEqual(chatbot_script.script_step_ids[1].message, "<p>Step 2</p>")
        self.assertEqual(chatbot_script.script_step_ids[1].sequence, 1)
        self.assertEqual(chatbot_script.script_step_ids[2].message, "<p>Step 3</p>")
        self.assertEqual(chatbot_script.script_step_ids[2].sequence, 2)

    def test_chatbot_steps_sequence_with_move_ui(self):
        self.start_tour(
            '/odoo',
            'im_livechat_chatbot_steps_sequence_with_move_tour',
            login='admin',
        )

        chatbot_script = self.env['chatbot.script'].search([('title', '=', 'Test Chatbot Sequence')])

        self.assertEqual(len(chatbot_script.script_step_ids), 6)


        self.assertEqual(chatbot_script.script_step_ids[0].message, "<p>Step 1</p>")
        self.assertEqual(chatbot_script.script_step_ids[0].sequence, 0)
        self.assertEqual(chatbot_script.script_step_ids[1].message, "<p>Step 5</p>")
        self.assertEqual(chatbot_script.script_step_ids[1].sequence, 1)
        self.assertEqual(chatbot_script.script_step_ids[2].message, "<p>Step 2</p>")
        self.assertEqual(chatbot_script.script_step_ids[2].sequence, 2)
        self.assertEqual(chatbot_script.script_step_ids[3].message, "<p>Step 3</p>")
        self.assertEqual(chatbot_script.script_step_ids[3].sequence, 3)
        self.assertEqual(chatbot_script.script_step_ids[4].message, "<p>Step 4</p>")
        self.assertEqual(chatbot_script.script_step_ids[4].sequence, 4)
        self.assertEqual(chatbot_script.script_step_ids[5].message, "<p>Step 6</p>")
        self.assertEqual(chatbot_script.script_step_ids[5].sequence, 5)
