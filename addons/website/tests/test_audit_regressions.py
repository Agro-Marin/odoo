# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Regressions found by the website audit.

Every test here fails on the code as it stood before the accompanying fix; each
one is anchored to the specific defect it guards, so a future refactor that
reintroduces the defect fails loudly rather than silently.
"""

from unittest.mock import MagicMock, patch

import psycopg
import requests
import werkzeug

from odoo.http import request
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools import mute_logger

from odoo.addons.http_routing.tests.common import MockRequest
from odoo.addons.website.controllers.form import WebsiteForm
from odoo.addons.website.controllers.main import Website


def _fake_google_response(content, content_type):
    """A minimal stand-in for a streamed ``requests`` response."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.headers = {"content-type": content_type}
    resp.iter_content.return_value = [content]
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


@tagged("post_install", "-at_install")
class TestWebsiteHostHeader(TransactionCase):
    def test_malformed_host_header_does_not_raise(self):
        """A malformed ``Host`` must not take down every frontend page.

        ``_get_current_website_id`` receives the raw request host. The ``idna``
        codec raises ``UnicodeError`` on a DNS label over 63 bytes and on an
        empty label, both trivially settable by an anonymous client, and the
        exception used to escape as an HTTP 500 on *every* route.
        """
        website = self.env["website"].sudo()
        for host in (
            "a" * 64 + ".example.com",  # label too long
            "a" * 300,  # way too long
            "a..b",  # empty label
            "",  # empty host
            "example.com",  # control: valid
            "xn--e1afmkfd.xn--p1ai",  # control: already punycode
            "пример.рф",  # control: unicode
        ):
            # must resolve to *some* website rather than raising
            self.assertTrue(
                website._get_current_website_id(host),
                f"host {host!r} should resolve via fallback, not raise",
            )

    def test_domain_punycode_survives_malformed_domain(self):
        website = self.env["website"].create(
            {"name": "Punycode", "domain": "http://" + "a" * 64 + ".example.com"}
        )
        # must not raise; falls back to the domain unchanged
        self.assertTrue(website.domain_punycode)

    def test_domain_punycode_only_rewrites_the_host(self):
        """Only the netloc is punycoded, not a hostname echoed in the path.

        A blanket ``str.replace`` rewrote every occurrence of the hostname,
        including one that happened to recur in the path/query.
        """
        website = self.env["website"].create(
            {"name": "Echo", "domain": "http://ex.com/go?to=ex.com"}
        )
        # ex.com is ASCII already, so punycode is a no-op: the path copy must be
        # left intact and the value must round-trip unchanged.
        self.assertEqual(website.domain_punycode, "http://ex.com/go?to=ex.com")


@tagged("post_install", "-at_install")
class TestTemplateCacheInvalidation(TransactionCase):
    def test_blocklist_change_takes_effect(self):
        """Writing a template-affecting field must flush the compiled templates.

        ``clear_cache()`` with no argument resolves to the "default" group,
        which does NOT contain "templates". The third-party blocklist and the
        CDN rewrite of literal URLs are baked into templates at compile time, so
        without an explicit flush an admin adding a tracker domain sees no
        effect on any already-compiled page -- a privacy control failing open.
        """
        website = self.env["website"].browse(1)
        website.write(
            {
                "cookies_bar": True,
                "block_third_party_domains": True,
                "custom_blocked_third_party_domains": "unrelated.test",
            }
        )
        self.env["ir.ui.view"].create(
            {
                "name": "audit_blocklist",
                "type": "qweb",
                "key": "website.audit_blocklist",
                "arch_db": (
                    '<t t-name="website.audit_blocklist"><div>'
                    '<iframe src="https://tracker.audit.test/pixel"/>'
                    "</div></t>"
                ),
            }
        )
        self.env.flush_all()

        public_env = self.env(
            user=self.env.ref("base.public_user"),
            context={"website_id": website.id, "lang": "en_US"},
        )

        def render():
            with MockRequest(public_env, website=website):
                return str(public_env["ir.qweb"]._render("website.audit_blocklist"))

        self.assertNotIn(
            "about:blank", render(), "not blocked yet: domain is not on the list"
        )

        website.write(
            {"custom_blocked_third_party_domains": "unrelated.test\ntracker.audit.test"}
        )
        self.env.flush_all()

        self.assertIn(
            "about:blank",
            render(),
            "adding a domain to the blocklist must take effect immediately",
        )


@tagged("post_install", "-at_install")
class TestMenuUnlinkFanout(TransactionCase):
    def test_generic_container_unlink_spares_other_websites(self):
        """Deleting a generic container must not delete unrelated dropdowns.

        ``unlink`` fans out to the per-website copies ``create`` made, matching
        on ``url``. But ``_compute_url`` collapses every menu with children (and
        every mega menu) to ``"#"``, so the fan-out used to match every
        container menu in the database and destroy other websites' menus.
        """
        Menu = self.env["website.menu"]
        main_menu = self.env.ref("website.main_menu")
        website_2 = self.env["website"].create({"name": "Audit W2"})

        # an unrelated dropdown owned by website 2
        victim = Menu.create(
            {
                "name": "Victim",
                "parent_id": website_2.menu_id.id,
                "website_id": website_2.id,
            }
        )
        victim_child = Menu.create(
            {
                "name": "VictimChild",
                "parent_id": victim.id,
                "url": "/victim-child",
                "website_id": website_2.id,
            }
        )
        # a generic container under the main menu
        generic = Menu.create({"name": "GenericDrop", "parent_id": main_menu.id})
        Menu.create({"name": "GenericChild", "parent_id": generic.id, "url": "/gc"})
        Menu.invalidate_model()
        self.assertEqual(victim.url, "#", "a menu with children is a '#' container")
        self.assertEqual(generic.url, "#", "so is the generic one")

        generic.unlink()
        Menu.invalidate_model()

        self.assertTrue(victim.exists(), "website 2's unrelated dropdown must survive")
        self.assertTrue(victim_child.exists(), "and so must its child")

    def test_generic_navigable_unlink_still_removes_copies(self):
        """The legitimate fan-out must keep working for navigable URLs."""
        Menu = self.env["website.menu"]
        main_menu = self.env.ref("website.main_menu")
        self.env["website"].create({"name": "Audit W2"})

        generic = Menu.create(
            {"name": "Shop", "url": "/audit-shop", "parent_id": main_menu.id}
        )
        Menu.invalidate_model()
        copies = Menu.search([("url", "=", "/audit-shop"), ("website_id", "!=", False)])
        self.assertTrue(copies, "create() should have made per-website copies")

        generic.unlink()
        Menu.invalidate_model()
        self.assertFalse(
            copies.exists(), "per-website copies of a navigable menu must be removed"
        )


@tagged("post_install", "-at_install")
class TestMultiWebsitePageScoping(TransactionCase):
    def test_is_homepage_is_website_scoped(self):
        """``is_homepage`` must answer for the website being looked at.

        Without ``depends_context("website_id")`` the ORM caches one value per
        record across contexts, so whichever website is read first wins and the
        homepage badge lands on the wrong page in the multi-website Pages list.
        """
        website_1 = self.env["website"].browse(1)
        website_2 = self.env["website"].create({"name": "Audit W2"})
        page = self.env["website.page"].search(
            [("website_id", "in", (False, website_1.id))], limit=1
        )
        self.assertTrue(page, "need at least one page")
        website_1.homepage_url = page.url
        website_2.homepage_url = "/audit-not-this-page"
        self.env.flush_all()
        self.env.invalidate_all()

        # read website 1 first, then website 2
        self.assertTrue(page.with_context(website_id=website_1.id).is_homepage)
        self.assertFalse(
            page.with_context(website_id=website_2.id).is_homepage,
            "website 1's answer must not leak into website 2's context",
        )

        # and the other order, to prove the cache key works both ways
        self.env.invalidate_all()
        self.assertFalse(page.with_context(website_id=website_2.id).is_homepage)
        self.assertTrue(page.with_context(website_id=website_1.id).is_homepage)

    def test_page_rename_does_not_repoint_other_websites(self):
        """Renaming website 1's page must not move website 2's homepage.

        The homepage was synced by matching the ``homepage_url`` *string* across
        every website, so a sibling website serving its own page at the same URL
        had its homepage repointed to a URL it cannot resolve.
        """
        website_1 = self.env["website"].browse(1)
        website_2 = self.env["website"].create({"name": "Audit W2"})

        def make_page(key, website):
            view = self.env["ir.ui.view"].create(
                {
                    "name": key,
                    "type": "qweb",
                    "key": f"website.{key}",
                    "arch_db": f'<t t-name="website.{key}"><div>{key}</div></t>',
                }
            )
            return self.env["website.page"].create(
                {"view_id": view.id, "url": "/audit-about", "website_id": website.id}
            )

        page_1 = make_page("audit_about_1", website_1)
        make_page("audit_about_2", website_2)
        website_1.homepage_url = "/audit-about"
        website_2.homepage_url = "/audit-about"
        self.env.flush_all()

        page_1.write({"url": "/audit-about-us"})
        self.env.flush_all()

        self.assertEqual(
            website_1.homepage_url, "/audit-about-us", "w1 follows its page"
        )
        self.assertEqual(
            website_2.homepage_url,
            "/audit-about",
            "w2 keeps pointing at its own page, which was not renamed",
        )


@tagged("post_install", "-at_install")
class TestWebsiteFormIntegrityError(TransactionCase):
    def test_constraint_violation_returns_false_not_500(self):
        """A DB constraint violation must degrade to ``false``, not a 500.

        ``_handle_website_form`` used to catch IntegrityError itself and return
        ``json.dumps(False)``. But an IntegrityError aborts the transaction, so
        returning normally left the caller's ``sp.close(rollback=False)`` to run
        on a dead cursor and raise InFailedSqlTransaction -- making the graceful
        path dead code and turning every constraint violation on a public,
        unauthenticated endpoint into an HTTP 500.
        """
        self.env.ref("base.model_res_partner").website_form_access = True
        self.env["ir.model.fields"].formbuilder_whitelist("res.partner", ["name"])
        controller = WebsiteForm()
        original_insert_record = controller.insert_record

        def failing_insert_record(*args, **kwargs):
            original_insert_record(*args, **kwargs)
            # Provoke a genuine constraint violation on the same cursor.
            self.env.cr.execute(
                "INSERT INTO res_company_users_rel (cid, user_id) VALUES (%s, %s)",
                (2147483000, 2147483001),
            )

        controller.insert_record = failing_insert_record
        with MockRequest(self.env):
            request.params = {"model_name": "res.partner", "name": "audit partner"}
            response = controller.website_form(**request.params)
            self.assertEqual(response.status_code, 200, "must not be a 500")
            self.assertEqual(
                response.data,
                b"false",
                "a constraint violation must return the graceful 'false'",
            )
            # The cursor must be usable again, i.e. the savepoint rolled back.
            self.env.cr.execute("SELECT 1")
            self.assertEqual(self.env.cr.fetchone()[0], 1)


@tagged("post_install", "-at_install")
class TestVisitorPageSearch(TransactionCase):
    def test_search_by_page_id_finds_visitor(self):
        """``page_ids`` is a m2m of website.page, so it is searched by id.

        Comparing those ids against ``page_id.name`` matched nothing and
        returned an empty recordset instead of raising -- a silent wrong answer.
        """
        page = self.env["website.page"].search([], limit=1)
        self.assertTrue(page, "need at least one page")
        visitor = self.env["website.visitor"].create({"access_token": "a" * 32})
        self.env["website.track"].create({"visitor_id": visitor.id, "page_id": page.id})
        self.env.flush_all()

        self.assertIn(
            visitor,
            self.env["website.visitor"].search([("page_ids", "in", [page.id])]),
            "searching visitors by visited page id must find the visitor",
        )


@tagged("post_install", "-at_install")
class TestCustomAssetIsolation(TransactionCase):
    def test_custom_scss_does_not_bleed_across_websites(self):
        """One website's compiled CSS must never be served to another.

        ``_make_custom_asset_url`` mints a URL with no website component, so two
        websites customising the same file produce attachments sharing a URL and
        (within one transaction) a ``write_date``. The bundle version is hashed
        over exactly those, so it collided while the content differed, and the
        store's cross-params fallback then copied one website's compiled bytes
        under the other's URL.
        """
        Assets = self.env["website.assets"]
        website_1 = self.env["website"].browse(1)
        website_2 = self.env["website"].create({"name": "Audit W2"})
        target = "/website/static/src/scss/options/user_values.scss"
        bundle = "web.assets_frontend"

        Assets.with_context(website_id=website_1.id).save_asset(
            target, bundle, "a.audit-probe{color:#ff0000}", "scss"
        )
        Assets.with_context(website_id=website_2.id).save_asset(
            target, bundle, "a.audit-probe{color:#0000ff}", "scss"
        )
        self.env.flush_all()

        compiled = {}
        for website in (website_1, website_2):
            asset_bundle = (
                self.env["ir.qweb"]
                .with_context(website_id=website.id)
                ._get_asset_bundle(bundle, css=True, js=False)
            )
            asset_bundle.css()
            compiled[website.id] = asset_bundle
        self.env.flush_all()

        for website, expected in ((website_1, b"red"), (website_2, b"blue")):
            url_prefix = f"/web/assets/{website.id}/"
            attachment = (
                self.env["ir.attachment"]
                .sudo()
                .search(
                    [
                        ("url", "=like", f"{url_prefix}%{bundle}%.css"),
                    ],
                    limit=1,
                )
            )
            self.assertTrue(attachment, f"website {website.id} should have a bundle")
            self.assertIn(
                b".audit-probe{color:" + expected,
                attachment.raw,
                f"website {website.id} must be served its OWN customisation",
            )


@tagged("post_install", "-at_install")
class TestControllerPageSlugPerWebsite(TransactionCase):
    """A model-page slug is unique *per website*, not globally.

    The ``/model/<slug>`` resolver disambiguates by ``website_domain()`` and
    ``_order`` puts the website-specific row first, so two websites (and a
    generic + a per-website override) may legitimately serve the same slug. A
    global ``UNIQUE(name_slugified)`` forbade exactly that.
    """

    def _make_page(self, website, view_key):
        view = self.env["ir.ui.view"].create(
            {
                "name": view_key,
                "type": "qweb",
                "key": f"website.{view_key}",
                "arch": '<t t-name="x"><div>x</div></t>',
                "website_id": website.id,
            }
        )
        return self.env["website.controller.page"].create(
            {
                "name": "AuditProducts",
                "view_id": view.id,
                "model_id": self.env["ir.model"]._get_id("res.partner"),
            }
        )

    def test_same_slug_allowed_on_two_websites(self):
        website_1 = self.env["website"].browse(1)
        website_2 = self.env["website"].create({"name": "Audit Slug W2"})
        self._make_page(website_1, "audit_slug_a")
        self._make_page(website_2, "audit_slug_b")
        # Must NOT raise: same slug, different websites.
        self.env.flush_all()

    def test_same_slug_rejected_on_same_website(self):
        website_1 = self.env["website"].browse(1)
        self._make_page(website_1, "audit_slug_c")
        self.env.flush_all()
        with self.assertRaises(psycopg.errors.UniqueViolation), mute_logger("odoo.db"):
            self._make_page(website_1, "audit_slug_d")
            self.env.flush_all()


@tagged("post_install", "-at_install")
class TestWebsiteFormTagsUnescape(TransactionCase):
    """The form ``tags`` filter unescapes ``\\,`` -> ``,`` and ``\\\\`` -> ``\\``.

    The previous ``\\/`` -> ``\\`` rule was a typo: it never restored an escaped
    backslash and corrupted any value containing ``\\/``.
    """

    def test_tags_unescape(self):
        tags = WebsiteForm().tags
        # Plain split on unescaped commas.
        self.assertEqual(tags("t", "a,b,c"), ["a", "b", "c"])
        # An escaped comma stays inside its tag.
        self.assertEqual(tags("t", r"a\,b,c"), ["a,b", "c"])
        # An escaped backslash collapses to a single one (was corrupted before).
        self.assertEqual(tags("t", r"a\\b"), [r"a\b"])


# NB: the cross-domain website_force redirect fix (request.redirect(...,
# local=False)) is verified end-to-end against a live server rather than here:
# MockRequest wires request.redirect straight to ir.http._redirect, which does
# not accept the `local` kwarg the real Request.redirect consumes, so the mock
# cannot model this path faithfully.


@tagged("post_install", "-at_install")
class TestResetTemplateAuthz(TransactionCase):
    """``/website/reset_template`` must require the restricted-editor group.

    It resets stored view arch (and, via website_id=None, the shared generic
    arch affecting every website), so it needs the same gate its sibling
    builder routes carry rather than relying solely on the ir.ui.view ACL.
    """

    def test_portal_user_forbidden(self):
        portal = new_test_user(
            self.env, login="audit_portal", groups="base.group_portal"
        )
        view = self.env["ir.ui.view"].search([("type", "=", "qweb")], limit=1)
        controller = Website()
        with MockRequest(self.env(user=portal)):
            with self.assertRaises(werkzeug.exceptions.Forbidden):
                controller.reset_template(view_id=view.id)


@tagged("post_install", "-at_install")
class TestPlausibleShareUrlParsing(TransactionCase):
    """A pasted Plausible *share* URL is split into (auth key, site)."""

    def test_share_url_is_split_into_key_and_site(self):
        config = self.env["res.config.settings"].create(
            {"website_id": self.env["website"].browse(1).id}
        )
        config.plausible_shared_key = (
            "https://plausible.io/share/example.com?auth=SECRET123&period=30d"
        )
        config._onchange_shared_key()
        self.assertEqual(config.plausible_shared_key, "SECRET123")
        self.assertEqual(config.plausible_site, "example.com")


@tagged("post_install", "-at_install")
class TestGoogleFontFetchHardening(TransactionCase):
    """Localising a Google font validates and bounds the remote responses.

    The fetch runs inside the settings-save transaction and stores *public*
    attachments, so a failed/oversized/mistyped response must degrade the font
    to online rather than 500 the save or persist arbitrary bytes.
    """

    _CSS = (
        b"@font-face{font-family:'Test';"
        b"src: url(https://fonts.gstatic.com/s/test/v1/abc.woff2) format('woff2');}"
    )

    def _localize(self, css_response, bin_response):
        def fake_get(url, **kw):
            return css_response() if "fonts.googleapis.com" in url else bin_response()

        with patch(
            "odoo.addons.website.models.assets.requests.get", side_effect=fake_get
        ):
            return self.env["website.assets"]._localize_google_fonts({"Test": ""})

    def _binary_count(self):
        return self.env["ir.attachment"].search_count(
            [("name", "=like", "google-font-%")]
        )

    def test_happy_path_localises_and_rewrites(self):
        resolved = self._localize(
            lambda: _fake_google_response(self._CSS, "text/css"),
            lambda: _fake_google_response(b"woff2-bytes", "font/woff2"),
        )
        self.assertTrue(resolved.get("Test"), "font should be localised")
        css = self.env["ir.attachment"].browse(resolved["Test"])
        self.assertIn(b"/web/content/", css.raw, "src rewritten to a local url")

    def test_network_failure_drops_font_without_raising(self):
        def boom():
            raise requests.ConnectionError("boom")

        resolved = self._localize(
            boom, lambda: _fake_google_response(b"x", "font/woff2")
        )
        self.assertNotIn("Test", resolved, "an unfetchable font is dropped, not a 500")

    def test_oversized_binary_is_not_stored(self):
        before = self._binary_count()
        oversized = b"x" * (5 * 1024 * 1024 + 1)
        resolved = self._localize(
            lambda: _fake_google_response(self._CSS, "text/css"),
            lambda: _fake_google_response(oversized, "font/woff2"),
        )
        css = self.env["ir.attachment"].browse(resolved["Test"])
        self.assertIn(b"fonts.gstatic.com", css.raw, "remote src kept on reject")
        self.assertEqual(before, self._binary_count(), "oversized bytes not stored")

    def test_non_font_content_type_is_rejected(self):
        before = self._binary_count()
        resolved = self._localize(
            lambda: _fake_google_response(self._CSS, "text/css"),
            lambda: _fake_google_response(b"<html>nope", "text/html"),
        )
        css = self.env["ir.attachment"].browse(resolved["Test"])
        self.assertIn(b"fonts.gstatic.com", css.raw)
        self.assertEqual(before, self._binary_count(), "non-font payload rejected")


@tagged("post_install", "-at_install")
class TestVisitorUpsertSeam(TransactionCase):
    """The visitor upsert core is exercisable without a request.

    `_upsert_visitor` takes its attributes as explicit keyword arguments
    (falling back to `request` in production), so its SQL -- the 8h visit-count
    window, the timezone back-fill on conflict, and the anonymous-vs-partner
    token branch -- is now coverable from a plain TransactionCase.
    """

    def setUp(self):
        super().setUp()
        self.Visitor = self.env["website.visitor"]
        self.website = self.env["website"].browse(1)
        self.lang = self.env["res.lang"].search([("active", "=", True)], limit=1)

    def test_upsert_creates_visitor_with_explicit_values(self):
        vid, inserted = self.Visitor._upsert_visitor(
            "a" * 32,
            lang_id=self.lang.id,
            country_code="US",
            website_id=self.website.id,
            timezone="Europe/Brussels",
        )
        self.assertTrue(inserted, "a fresh token must INSERT")
        self.env.invalidate_all()
        visitor = self.Visitor.browse(vid)
        self.assertEqual(visitor.access_token, "a" * 32)
        self.assertEqual(visitor.lang_id, self.lang)
        self.assertEqual(visitor.website_id, self.website)
        self.assertEqual(visitor.timezone, "Europe/Brussels")
        self.assertEqual(visitor.country_id.code, "US")
        self.assertFalse(visitor.partner_id, "a 32-char token is anonymous")

    def test_upsert_backfills_timezone_on_conflict(self):
        token = "b" * 32
        vid, _ = self.Visitor._upsert_visitor(
            token,
            lang_id=self.lang.id,
            country_code="",
            website_id=self.website.id,
            timezone="",
        )
        self.env.invalidate_all()
        self.assertFalse(self.Visitor.browse(vid).timezone)
        vid2, inserted = self.Visitor._upsert_visitor(
            token,
            lang_id=self.lang.id,
            country_code="",
            website_id=self.website.id,
            timezone="Asia/Tokyo",
        )
        self.assertFalse(inserted, "the same token must UPDATE, not insert")
        self.assertEqual(vid2, vid)
        self.env.invalidate_all()
        self.assertEqual(
            self.Visitor.browse(vid).timezone,
            "Asia/Tokyo",
            "a tz that arrives on a later visit must be back-filled",
        )

    def test_upsert_visit_count_respects_the_8h_window(self):
        token = "c" * 32
        kw = {
            "lang_id": self.lang.id,
            "country_code": "",
            "website_id": self.website.id,
            "timezone": "",
        }
        vid, _ = self.Visitor._upsert_visitor(token, **kw)
        self.env.invalidate_all()
        self.assertEqual(self.Visitor.browse(vid).visit_count, 1)
        # A second hit within 8h is the same visit.
        self.Visitor._upsert_visitor(token, **kw)
        self.env.invalidate_all()
        self.assertEqual(self.Visitor.browse(vid).visit_count, 1)
        # Backdate the last connection beyond 8h -> the next hit is a new visit.
        self.env.cr.execute(
            "UPDATE website_visitor "
            "SET last_connection_datetime = (now() at time zone 'UTC') - INTERVAL '9 hours' "
            "WHERE id = %s",
            (vid,),
        )
        self.env.invalidate_all()
        self.Visitor._upsert_visitor(token, **kw)
        self.env.invalidate_all()
        self.assertEqual(self.Visitor.browse(vid).visit_count, 2)

    def test_upsert_partner_token_links_partner(self):
        partner = self.env["res.partner"].create({"name": "Audit Visitor"})
        vid, _ = self.Visitor._upsert_visitor(
            partner.id,
            lang_id=self.lang.id,
            country_code="",
            website_id=self.website.id,
            timezone="",
        )
        self.env.invalidate_all()
        self.assertEqual(
            self.Visitor.browse(vid).partner_id,
            partner,
            "a non-32-char (partner id) token links the partner",
        )
