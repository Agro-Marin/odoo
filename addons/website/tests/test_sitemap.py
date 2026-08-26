import ast
import functools
import inspect
import textwrap
import types
from unittest.mock import patch

from odoo.tests import HttpCase, TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestWebsiteSitemap(TransactionCase):
    def test_sitemap_page_lastmod(self):
        website = self.env["website"].search([], limit=1)
        page_url = "/test-page"
        Page = self.env["website.page"]
        page = Page.create(
            {
                "name": "Test Page",
                "website_id": website.id,
                "url": page_url,
                "type": "qweb",
                "arch": '<t t-call="website.layout"/>',
                "is_published": True,
            }
        )
        View = self.env["ir.ui.view"]

        def set_write_dates(page_date, view_date):
            self.env.cr.execute(
                "UPDATE website_page SET write_date = %s WHERE id = %s",
                (page_date, page.id),
            )
            self.env.cr.execute(
                "UPDATE ir_ui_view SET write_date = %s WHERE id = %s",
                (view_date, page.view_id.id),
            )
            View.invalidate_model(["write_date"])
            Page.invalidate_model(["write_date", "view_write_date"])
            self.assertEqual(str(page.write_date), page_date)
            self.assertEqual(str(page.view_id.write_date), view_date)

        def get_sitemap_lastmod():
            pages = website._enumerate_pages()
            return next(p["lastmod"] for p in pages if p["loc"] == page_url)

        old_date = "2002-05-06 12:00:00"

        new_date = "2014-05-15 12:00:00"
        set_write_dates(new_date, old_date)
        self.assertEqual(str(get_sitemap_lastmod()), new_date[:10])

        new_date2 = "2015-10-01 12:00:00"
        set_write_dates(old_date, new_date2)
        self.assertEqual(str(get_sitemap_lastmod()), new_date2[:10])

    def test_sitemap_dedup_overridden_controllers(self):
        website = self.env["website"].search([], limit=1)

        def fake_sitemap_callable(env, rule, qs):
            yield {"loc": "/dupe"}
            yield {"loc": "/dupe/"}

        class FakeEndpoint:
            routing = {"sitemap": fake_sitemap_callable}

        class FakeRule:
            endpoint = FakeEndpoint()

        class FakeRouter:
            def iter_rules(self):
                return [FakeRule()]

        with patch(
            "odoo.addons.website.models.ir_http.IrHttp.routing_map",
            autospec=True,
            return_value=FakeRouter(),
        ):
            locs = list(website.with_user(website.user_id)._enumerate_pages())

        dupes = [l["loc"] for l in locs if l["loc"].startswith("/dupe")]
        self.assertEqual(dupes, ["/dupe"])

    def test_sitemap_callable_dedup_with_partial_and_bound(self):
        website = self.env["website"].search([], limit=1)

        call_count = {"n": 0}

        class CallableHolder:
            def sitemap(self, env, rule, qs):
                call_count["n"] += 1
                yield {"loc": "/once"}

        holder = CallableHolder()

        class EndpointBound:
            routing = {"sitemap": holder.sitemap}

        class RuleBound:
            endpoint = EndpointBound()

        class EndpointPartial:
            routing = {"sitemap": functools.partial(holder.sitemap)}

        class RulePartial:
            endpoint = EndpointPartial()

        class FakeRouter:
            def iter_rules(self):
                return [RuleBound(), RulePartial()]

        with patch(
            "odoo.addons.website.models.ir_http.IrHttp.routing_map",
            autospec=True,
            return_value=FakeRouter(),
        ):
            locs = list(website.with_user(website.user_id)._enumerate_pages())

        self.assertEqual(call_count["n"], 1)
        self.assertIn({"loc": "/once"}, locs)

    def test_sitemap_callbacks_ignore_their_rule_argument(self):
        offenders = []
        seen = set()
        for rule in self.env["ir.http"].routing_map().iter_rules():
            func = rule.endpoint.routing.get("sitemap")
            if not callable(func):
                continue
            if isinstance(func, functools.partial):
                func = func.func
            if isinstance(func, types.MethodType):
                func = func.__func__
            if func in seen:
                continue
            seen.add(func)
            try:
                source = inspect.getsource(func)
            except OSError, TypeError:
                continue
            tree = ast.parse(textwrap.dedent(source))
            defs = [
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            if not defs:
                continue
            params = [arg.arg for arg in defs[0].args.args]
            if "rule" not in params:
                continue
            body = ast.Module(body=defs[0].body, type_ignores=[])
            if any(
                isinstance(node, ast.Name) and node.id == "rule"
                for node in ast.walk(body)
            ):
                offenders.append(f"  {func.__module__}.{func.__qualname__}")

        self.assertFalse(
            offenders,
            "%s sitemap callback(s) read the `rule` they are handed, which the "
            "dedup in `_enumerate_pages` assumes none of them does -- so only "
            "the first of the endpoint's URL patterns would ever be "
            "generated:\n%s" % (len(offenders), "\n".join(offenders)),
        )


@tagged("-at_install", "post_install")
class TestWebsiteSitemapHost(HttpCase):
    def test_sitemap_ignores_host_header(self):
        website = self.env["website"].search([], limit=1)
        website.domain = False
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("web.base.url", "http://canonical.example")
        ICP.set_param("web.base.url.freeze", "1")
        self.env["website.page"].create(
            {
                "name": "Sitemap Host Test",
                "website_id": website.id,
                "url": "/sitemap-host-test",
                "type": "qweb",
                "arch": '<t t-call="website.layout"/>',
                "is_published": True,
            }
        )
        Attachment = self.env["ir.attachment"].sudo()
        dom = [
            ("type", "=", "binary"),
            ("url", "=like", "/sitemap-%d-%%" % website.id),
        ]
        Attachment.search(dom).unlink()

        r1 = self.url_open("/sitemap.xml", headers={"Host": "evil-a.example"})
        self.assertEqual(r1.status_code, 200)
        n1 = Attachment.search_count(dom)
        self.assertTrue(n1, "a sitemap should have been generated")

        r2 = self.url_open("/sitemap.xml", headers={"Host": "evil-b.example"})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(
            Attachment.search_count(dom),
            n1,
            "Varying the Host must not create new sitemap attachments.",
        )
        self.assertNotIn(b"evil-a.example", r2.content)
        self.assertNotIn(b"evil-b.example", r2.content)
        self.assertIn(b"canonical.example", r2.content)
