from odoo.tests import TransactionCase


class TestMenuUrlOnCreate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env["website"].search([], limit=1)
        cls.page = cls.env["website.page"].create(
            {
                "name": "Menu target",
                "type": "qweb",
                "arch": "<div/>",
                "key": "website.test_menu_target",
                "url": "/menu-target",
                "website_id": cls.website.id,
            }
        )

    def test_a_menu_on_a_page_links_to_the_page(self):
        menu = self.env["website.menu"].create(
            {"name": "Target", "page_id": self.page.id, "website_id": self.website.id}
        )

        self.assertEqual(menu.url, "/menu-target")

    def test_a_menu_with_neither_page_nor_url_links_nowhere(self):
        menu = self.env["website.menu"].create(
            {"name": "Nowhere", "website_id": self.website.id}
        )

        self.assertEqual(menu.url, "#")

    def test_an_explicit_url_wins(self):
        menu = self.env["website.menu"].create(
            {"name": "Shop", "url": "/shop", "website_id": self.website.id}
        )

        self.assertEqual(menu.url, "/shop")
