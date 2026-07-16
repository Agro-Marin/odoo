import lxml.html

from odoo.tests import HttpCase, tagged


@tagged("-at_install", "post_install")
class TestMultiWebsite(HttpCase):
    def test_multi_website_switch(self):
        Website = self.env["website"]

        website_1 = Website.create({"name": "Website 1"})
        website_2 = Website.create({"name": "Website 2"})

        self.authenticate("admin", "admin")
        base_url = website_1.get_base_url()

        res1 = self.url_open(base_url + "/website/force/%s" % website_2.id)
        res2 = self.url_open(base_url + "/website/force/%s" % website_1.id)
        website_2_tree = lxml.html.fromstring(res1.content)
        website_1_tree = lxml.html.fromstring(res2.content)

        data_obj_1 = website_1_tree.xpath("//html/@data-main-object")[0]
        data_obj_2 = website_2_tree.xpath("//html/@data-main-object")[0]

        website_id_1 = website_1_tree.xpath("//html/@data-website-id")[0]
        website_id_2 = website_2_tree.xpath("//html/@data-website-id")[0]

        self.assertNotEqual(data_obj_1, data_obj_2)
        self.assertNotEqual(website_id_1, website_id_2)

    def test_page_of_other_website_is_not_served(self):
        """A published page scoped to website 2 must not be served on website 1
        (multi-website content isolation)."""
        Website = self.env["website"]
        website_1 = Website.browse(1)
        website_2 = Website.create({"name": "Isolation Site"})
        view = self.env["ir.ui.view"].create(
            {
                "name": "Iso Page",
                "type": "qweb",
                "arch": '<t t-name="website.iso_page"><t t-call="website.layout">'
                '<div id="wrap">secret</div></t></t>',
                "key": "website.iso_page",
            }
        )
        self.env["website.page"].create(
            {
                "view_id": view.id,
                "url": "/iso-secret",
                "website_id": website_2.id,
                "is_published": True,
            }
        )
        # website_1 is the one served on the default host.
        res = self.url_open(website_1.get_base_url() + "/iso-secret")
        self.assertEqual(
            res.status_code,
            404,
            "a page scoped to website 2 must not be served on website 1",
        )

    def test_website_force_requires_privileges(self):
        """/website/force must not switch the session website for a user lacking
        group_multi_website + group_website_restricted_editor."""
        Website = self.env["website"]
        website_2 = Website.create({"name": "Forced Site"})
        # Unauthenticated (public) user has neither required group.
        res = self.url_open(
            Website.browse(1).get_base_url() + "/website/force/%s" % website_2.id,
            allow_redirects=True,
        )
        ids = lxml.html.fromstring(res.content).xpath("//html/@data-website-id")
        self.assertTrue(ids, "a page should have rendered")
        self.assertNotEqual(
            int(ids[0]),
            website_2.id,
            "a non-privileged user must not force-switch to another website",
        )
