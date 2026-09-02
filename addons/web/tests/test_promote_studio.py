from odoo.tests.common import HttpCase, tagged


@tagged("-at_install", "post_install", "web_tour", "web_promote_studio")
class TestPromoteStudio(HttpCase):
    def test_studio_list_upsell(self):
        invoice_action = self.env.ref(
            "account.action_move_out_invoice_type", raise_if_not_found=False
        )
        if not invoice_action:
            self.skipTest("account is not installed")
        self.start_tour(
            "/odoo/action-account.action_move_out_invoice_type",
            "web.test_studio_list_upsell",
            login="admin",
        )

    def test_studio_no_list_upsell_if_blacklisted(self):
        knowledge_action = self.env.ref(
            "knowledge.knowledge_article_action", raise_if_not_found=False
        )
        if not knowledge_action:
            self.skipTest("knowledge is not installed")
        self.start_tour(
            "/odoo/action-knowledge.knowledge_article_action",
            "web.test_studio_no_list_upsell_if_blacklisted",
            login="admin",
        )
