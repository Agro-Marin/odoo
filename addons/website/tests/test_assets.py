import re

import odoo.tests


@odoo.tests.common.tagged("post_install", "-at_install")
class TestWebsiteAssets(odoo.tests.HttpCase):
    def test_01_multi_domain_assets_generation(self):
        Website = self.env["website"]
        Attachment = self.env["ir.attachment"]
        Website.create({"name": "Second Website"})
        [w.write({"domain": f"inactive-{w.id}.test"}) for w in Website.search([])]
        domain_1 = f"http://127.0.0.1:{self.http_port()}"
        domain_2 = f"http://localhost:{self.http_port()}"
        Website.browse(1).domain = domain_1

        self.authenticate("admin", "admin")
        self.env["website.assets"].with_context(website_id=1).make_scss_customization(
            "/website/static/src/scss/options/colors/user_color_palette.scss",
            {"o-cc1-bg": "'400'"},
        )

        def get_last_backend_asset_attach_id():
            return Attachment.search(
                [
                    ("name", "=", "web.assets_backend.min.js"),
                ],
                order="id desc",
                limit=1,
            ).id

        def check_asset():
            self.assertEqual(
                last_backend_asset_attach_id, get_last_backend_asset_attach_id()
            )

        last_backend_asset_attach_id = get_last_backend_asset_attach_id()

        self.url_open(domain_1 + "/odoo")
        check_asset()
        self.url_open(domain_2 + "/odoo")
        check_asset()
        self.url_open(domain_1 + "/odoo")
        check_asset()
        self.url_open(domain_2 + "/odoo")
        check_asset()
        self.url_open(domain_1 + "/odoo")
        check_asset()

    def test_02_t_cache_invalidation(self):
        self.authenticate(None, None)
        page = self.url_open("/").text
        public_assets_links = re.findall(
            r'(/web/assets/\d+/\w{7}/web.assets_frontend\..+)"/>', page
        )
        self.assertTrue(public_assets_links)
        self.authenticate("admin", "admin")
        page = self.url_open("/").text
        admin_assets_links = re.findall(
            r'(/web/assets/\d+/\w{7}/web.assets_frontend\..+)"/>', page
        )
        self.assertTrue(admin_assets_links)

        self.assertEqual(public_assets_links, admin_assets_links)

        snippets = self.env["ir.asset"].search(
            [
                (
                    "path",
                    "=like",
                    "website/static/src/snippets/s_social_media/000.scss",
                ),
                ("bundle", "=", "web.assets_frontend"),
            ]
        )
        self.assertTrue(snippets)
        write_dates = snippets.mapped("write_date")
        snippets.write({"active": False})
        snippets.flush_recordset()
        self.assertNotEqual(write_dates, snippets.mapped("write_date"))

        page = self.url_open("/").text
        new_admin_assets_links = re.findall(
            r'(/web/assets/\d+/\w{7}/web.assets_frontend\..+)"/>', page
        )
        self.assertTrue(new_admin_assets_links)

        self.assertEqual(public_assets_links, admin_assets_links)
        self.assertNotEqual(
            new_admin_assets_links,
            admin_assets_links,
            "we expect a change since ir_assets were written",
        )

        self.authenticate(None, None)
        page = self.url_open("/").text

        new_public_assets_links = re.findall(
            r'(/web/assets/\d+/\w{7}/web.assets_frontend\..+)"/>', page
        )
        self.assertEqual(
            new_admin_assets_links,
            new_public_assets_links,
            "caches should have been invalidated for public user too",
        )

    def test_invalid_unlink(self):
        self.env["ir.attachment"].search([("url", "=like", "/web/assets/%")]).unlink()

        asset_bundle_xmlid = "web.assets_frontend"
        website_default = self.env["website"].search([], limit=1)

        code = b"document.body.dataset.hello = 'world';"
        attach = self.env["ir.attachment"].create(
            {
                "name": "EditorExtension.css",
                "mimetype": "text/css",
                "raw": code,
            }
        )
        custom_url = "/_custom/web/content/%s/%s" % (attach.id, attach.name)
        attach.url = custom_url

        self.env["ir.asset"].create(
            {
                "name": "EditorExtension",
                "bundle": asset_bundle_xmlid,
                "path": custom_url,
                "website_id": website_default.id,
            }
        )

        website_bundle = self.env["ir.qweb"]._get_asset_bundle(
            asset_bundle_xmlid, assets_params={"website_id": website_default.id}
        )
        self.assertIn(custom_url, [f["url"] for f in website_bundle.files])
        base_website_css_version = website_bundle.get_version("css")

        no_website_bundle = self.env["ir.qweb"]._get_asset_bundle(asset_bundle_xmlid)
        self.assertNotIn(custom_url, [f["url"] for f in no_website_bundle.files])
        self.assertNotEqual(
            no_website_bundle.get_version("css"), base_website_css_version
        )

        website_attach = website_bundle.css()
        self.assertTrue(website_attach.exists())
        no_website_bundle.css()
        self.assertTrue(
            website_attach.exists(),
            "attachment for website should still exist after generating attachment for no website",
        )


@odoo.tests.tagged("-at_install", "post_install")
class TestWebAssets(odoo.tests.HttpCase):
    def test_assets_url_validation(self):
        website_id = self.env["website"].search([], limit=1, order="id desc").id

        with odoo.tools.mute_logger("odoo.addons.web.controllers.binary"):
            self.assertEqual(
                self.url_open(
                    f"/web/assets/{website_id}/debug/hello/web.assets_frontend.css",
                    allow_redirects=False,
                ).status_code,
                404,
                "unexpected direction extra",
            )
            self.assertEqual(
                self.url_open(
                    f"/web/assets/{website_id}/debug/web.assets_f_ontend.js",
                    allow_redirects=False,
                ).status_code,
                404,
                "bundle name contains `_` and should be escaped wildcard",
            )
            self.assertEqual(
                self.url_open(
                    f"/web/assets/{website_id}/debug/web.assets_frontend.rtl.js",
                    allow_redirects=False,
                ).status_code,
                404,
                "js cannot have `rtl` has extra",
            )
            self.assertEqual(
                self.url_open(
                    f"/web/assets/{website_id}/debug/web.assets_frontend.rtl.js",
                    allow_redirects=False,
                ).status_code,
                404,
                "js cannot have `rtl` has extra",
            )
            self.assertEqual(
                self.url_open(
                    f"/web/{website_id + 1}/assets/debug/web.assets_frontend.css",
                    allow_redirects=False,
                ).status_code,
                404,
                "website_id does not exist",
            )
            self.assertEqual(
                self.url_open(
                    f"/web/assets/{website_id}/debug/web.assets_frontend.aa.css",
                    allow_redirects=False,
                ).status_code,
                404,
                "invalid direction",
            )
            self.assertEqual(
                self.url_open(
                    f"/web/assets/{website_id}/any/web.assets_frontend.min.rtl.css",
                    allow_redirects=False,
                ).status_code,
                404,
                "min and direction inverted",
            )
            self.assertEqual(
                self.url_open(
                    f"/web/assets/{website_id}/any/web.assets_frontend.js",
                    allow_redirects=False,
                ).status_code,
                404,
                "missing min in non debug mode",
            )

        self.assertEqual(
            self.url_open(
                "/web/assets/debug/web.assets_frontend.css", allow_redirects=False
            ).status_code,
            200,
        )
        self.assertEqual(
            self.url_open(
                "/web/assets/debug/web.assets_frontend.js", allow_redirects=False
            ).status_code,
            200,
        )
        self.assertEqual(
            self.url_open(
                "/web/assets/debug/web.assets_frontend.rtl.css", allow_redirects=False
            ).status_code,
            200,
        )
        self.assertEqual(
            self.url_open(
                f"/web/assets/{website_id}/debug/web.assets_frontend.css",
                allow_redirects=False,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.url_open(
                f"/web/assets/{website_id}/debug/web.assets_frontend.rtl.css",
                allow_redirects=False,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.url_open(
                f"/web/assets/{website_id}/debug/web.assets_frontend.js",
                allow_redirects=False,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.url_open(
                f"/web/assets/{website_id}/any/web.assets_frontend.rtl.min.css",
                allow_redirects=False,
            ).status_code,
            200,
        )

        self.assertEqual(
            self.url_open(
                f"/web/assets/{website_id}/any/web.assets_frontend.min.css",
                allow_redirects=False,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.url_open(
                f"/web/assets/{website_id}/any/web.assets_frontend.min.js",
                allow_redirects=False,
            ).status_code,
            200,
        )

        invalid_version = "1234567"
        self.assertEqual(
            self.url_open(
                f"/web/assets/{website_id}/{invalid_version}/web.assets_frontend.min.css",
                allow_redirects=False,
            )
            .headers["location"]
            .split("/assets/")[1],
            self.env["ir.qweb"]
            ._get_asset_bundle(
                "web.assets_frontend", assets_params={"website_id": website_id}
            )
            .get_link("css")
            .split("/assets/")[1],
        )

    def test_ensure_correct_website_asset(self):
        website_id = self.env["website"].search([], limit=1, order="id asc").id
        unique = (
            self.env["ir.qweb"]
            ._get_asset_bundle("web.assets_frontend")
            .get_version("js")
        )
        base_url = self.env["ir.asset"]._get_asset_bundle_url(
            "web.assets_frontend.min.js", "%", {}
        )
        base_url_versioned = self.env["ir.asset"]._get_asset_bundle_url(
            "web.assets_frontend.min.js", unique, {}
        )
        website_url = self.env["ir.asset"]._get_asset_bundle_url(
            "web.assets_frontend.min.js", "%", {"website_id": website_id}
        )
        website_url_versioned = self.env["ir.asset"]._get_asset_bundle_url(
            "web.assets_frontend.min.js", unique, {"website_id": website_id}
        )

        self.env["ir.attachment"].search(
            [("url", "=like", "%web.assets_frontend.min.js")]
        ).unlink()

        self.assertEqual(
            self.url_open(website_url, allow_redirects=False).status_code, 200
        )
        self.assertEqual(
            self.env["ir.attachment"]
            .search([("url", "=like", "%web.assets_frontend.min.js")])
            .mapped("url"),
            [website_url_versioned],
            "Only the website asset is expected to be present",
        )

        self.assertEqual(
            self.url_open(base_url, allow_redirects=False).status_code, 200
        )
        self.assertCountEqual(
            self.env["ir.attachment"]
            .search([("url", "=like", "%web.assets_frontend.min.js")])
            .mapped("url"),
            [base_url_versioned, website_url_versioned],
            "the base asset must be generated alongside the surviving website one",
        )
