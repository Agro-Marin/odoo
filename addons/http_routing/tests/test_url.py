# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import MagicMock, Mock, patch

import werkzeug.exceptions
import werkzeug.routing

from odoo.tests import TransactionCase, tagged

from .common import MockRequest


@tagged("-at_install", "post_install")
class TestUrlCommon(TransactionCase):
    """Shared multi-lang fixture for the URL-generation helpers.

    ``fr_FR`` (url_code ``fr``) is activated next to ``en_US`` (url_code
    ``en``), and ``en_US`` is pinned as the frontend default, so every branch
    of the lang insertion/stripping/replacement logic is reachable.

    All requests are simulated with ``MockRequest(..., mock_router=False)``:
    the helpers then match and build against the *real* routing map, using
    ``/website/translations`` -- the sole ``website=True`` multilang endpoint
    this module ships -- as the multilang route.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR").url_code = "fr"
        cls.env["ir.default"].set("res.partner", "lang", "en_US")
        cls.IrHttp = cls.env["ir.http"]
        # /website/translations: the one frontend multilang route available
        # with only http_routing installed (see test_lang.TestLangLadder).
        cls.EP = "/website/translations"


class TestUrlLang(TestUrlCommon):
    """Unit coverage for ``ir.http._url_for`` / ``_url_lang``.

    These back every ``url_for()`` call in frontend QWeb, yet had no coverage
    inside http_routing (only website's integration suite exercised them).
    """

    def test_adds_context_lang_when_not_default(self):
        with MockRequest(self.env, context={"lang": "fr_FR"}, mock_router=False):
            self.assertEqual(self.IrHttp._url_for(self.EP), "/fr" + self.EP)

    def test_default_context_lang_untouched(self):
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(self.IrHttp._url_for(self.EP), self.EP)

    def test_query_string_preserved(self):
        with MockRequest(self.env, context={"lang": "fr_FR"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_for(self.EP + "?x=1&x=2"),
                "/fr" + self.EP + "?x=1&x=2",
            )

    def test_trailing_slash_dropped_on_insert(self):
        with MockRequest(self.env, context={"lang": "fr_FR"}, mock_router=False):
            self.assertEqual(self.IrHttp._url_for(self.EP + "/"), "/fr" + self.EP)

    def test_force_lang_replaces_existing_lang(self):
        with MockRequest(self.env, context={"lang": "fr_FR"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_for("/fr" + self.EP, "en_US"), "/en" + self.EP
            )

    def test_default_lang_prefix_stripped(self):
        # The default lang is only kept when explicitly forced (see above);
        # a stray /en prefix is removed otherwise.
        with MockRequest(self.env, context={"lang": "fr_FR"}, mock_router=False):
            self.assertEqual(self.IrHttp._url_for("/en" + self.EP), self.EP)

    def test_lang_placeholder_passthrough(self):
        # '[lang]' (used by url_return) is not a known url_code: it must be
        # inserted verbatim.
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_for(self.EP, "[lang]"), "/[lang]" + self.EP
            )

    def test_absolute_url_untouched(self):
        with MockRequest(self.env, context={"lang": "fr_FR"}, mock_router=False):
            url = "https://odoo.com" + self.EP
            self.assertEqual(self.IrHttp._url_for(url), url)

    def test_invalid_url_untouched(self):
        # e.g. invalid IPv6 netloc: urlparse raises ValueError
        with MockRequest(self.env, context={"lang": "fr_FR"}, mock_router=False):
            self.assertEqual(self.IrHttp._url_for("http://]"), "http://]")

    def test_non_multilang_urls_untouched(self):
        with MockRequest(self.env, context={"lang": "fr_FR"}, mock_router=False):
            self.assertEqual(self.IrHttp._url_for("/web/login"), "/web/login")
            self.assertEqual(
                self.IrHttp._url_for("/foo/static/src/x.js"), "/foo/static/src/x.js"
            )


class TestIsMultilangUrl(TestUrlCommon):
    """Unit coverage for ``ir.http._is_multilang_url`` against real routes."""

    def setUp(self):
        super().setUp()
        # url_rewrite memoizes (path, query_args) -> endpoint lookups in the
        # registry-level "routing.rewrites" ormcache; drop this class's probe
        # entries instead of leaking them to the rest of the suite. Dotted
        # names cannot be cleared directly -- clear their composite group.
        self.addCleanup(self.registry.clear_cache, "routing")

    def test_multilang_route(self):
        with MockRequest(self.env, mock_router=False):
            self.assertTrue(self.IrHttp._is_multilang_url(self.EP))

    def test_lang_prefix_is_ignored_for_matching(self):
        with MockRequest(self.env, mock_router=False):
            self.assertTrue(self.IrHttp._is_multilang_url("/fr" + self.EP))

    def test_unrouted_path_is_multilang(self):
        # everything not under /static/ or /web/ without an endpoint (e.g. a
        # CMS page) is considered translatable
        with MockRequest(self.env, mock_router=False):
            self.assertTrue(self.IrHttp._is_multilang_url("/no/such/page"))

    def test_static_and_web_are_not_multilang(self):
        with MockRequest(self.env, mock_router=False):
            self.assertFalse(self.IrHttp._is_multilang_url("/web/login"))
            self.assertFalse(self.IrHttp._is_multilang_url("/foo/static/x.js"))


class TestUrlLocalized(TestUrlCommon):
    """Unit coverage for ``ir.http._url_localized``: the happy rebuild path
    and, critically, every "cannot rebuild -> degrade to the given URL"
    fallback. The degradations used to be able to escape as HTTP exceptions
    (werkzeug ``RequestRedirect`` from a 308 rewrite rule, ``MethodNotAllowed``
    from probing with the current request's method) and abort the surrounding
    render; pin the contract: ``_url_localized`` never raises for a URL it
    cannot rebuild.
    """

    def test_happy_path_prefixes_lang(self):
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_localized(self.EP, lang_code="fr_FR"),
                "/fr" + self.EP,
            )

    def test_default_lang_no_prefix(self):
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_localized(self.EP, lang_code="en_US"), self.EP
            )

    def test_force_default_lang_prefixes_anyway(self):
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_localized(
                    self.EP, lang_code="en_US", force_default_lang=True
                ),
                "/en" + self.EP,
            )

    def test_canonical_domain_joined_and_query_dropped(self):
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_localized(
                    self.EP + "?a=b",
                    lang_code="fr_FR",
                    canonical_domain="https://example.com",
                ),
                "https://example.com/fr" + self.EP,
            )

    def test_query_string_preserved(self):
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_localized(self.EP + "?a=b", lang_code="fr_FR"),
                "/fr" + self.EP + "?a=b",
            )

    def test_unknown_lang_falls_back_to_request_lang(self):
        # An unknown/inactive code resolves to a dummy LangData; the request
        # lang (en_US = default) must be used instead of splicing "/False/".
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_localized(self.EP, lang_code="xx_XX"), self.EP
            )

    def test_unmatched_url_degrades(self):
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_localized("/no/such/page-4", lang_code="fr_FR"),
                "/fr/no/such/page-4",
            )

    def test_unmatched_url_quoting(self):
        # The degradation path re-quotes the URL like ``router.build`` would:
        # existing percent-escapes must survive (no "%C3%A9" -> "%25C3%25A9"
        # double-encoding) and a raw space must become "%20", not "+".
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_localized("/no/such/caf%C3%A9-4", lang_code="fr_FR"),
                "/fr/no/such/caf%C3%A9-4",
            )
            self.assertEqual(
                self.IrHttp._url_localized("/no such/page-4", lang_code="fr_FR"),
                "/fr/no%20such/page-4",
            )

    def test_request_redirect_degrades(self):
        # A path sitting under a 308 rewrite rule (website.rewrite) makes the
        # match probe raise werkzeug's RequestRedirect -- an HTTPException that
        # must NOT escape and abort the render with a stray 308.
        self.patch(
            self.registry["ir.http"],
            "_match",
            Mock(side_effect=werkzeug.routing.RequestRedirect("http://x/moved")),
        )
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_localized(self.EP, lang_code="fr_FR"),
                "/fr" + self.EP,
            )

    def test_method_not_allowed_degrades(self):
        # The probe matches with the *current* request's method; a POST
        # request localizing a GET-only URL must degrade, not 500.
        self.patch(
            self.registry["ir.http"],
            "_match",
            Mock(side_effect=werkzeug.exceptions.MethodNotAllowed()),
        )
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_localized(self.EP, lang_code="fr_FR"),
                "/fr" + self.EP,
            )


class TestUrlRewrite(TestUrlCommon):
    """Unit coverage for ``ir.http.url_rewrite`` edge cases."""

    def setUp(self):
        super().setUp()
        # Drop this class's probe entries from the registry-level
        # "routing.rewrites" ormcache (same rationale as TestIsMultilangUrl).
        self.addCleanup(self.registry.clear_cache, "routing")

    def test_redirect_loop_degrades(self):
        # Two redirect rules pointing at each other (e.g. website.rewrite 308
        # rules /a -> /b and /b -> /a, creatable because the constraint only
        # forbids direct self-redirects) must degrade to (path, False) with a
        # warning instead of dying on RecursionError -- which would 500 every
        # render generating a URL through the looping path.
        targets = {"/loop/a": "/loop/b", "/loop/b": "/loop/a"}

        def fake_match(path, method=None):
            raise werkzeug.routing.RequestRedirect("http://x" + targets[path])

        router = MagicMock()
        router.return_value.bind.return_value.match.side_effect = fake_match
        with (
            MockRequest(self.env, mock_router=False),
            patch("odoo.http.root.get_db_router", router),
            self.assertLogs(
                "odoo.addons.http_routing.models.ir_http", level="WARNING"
            ) as capture,
        ):
            path, func = self.env["ir.http"].url_rewrite("/loop/a")
        self.assertEqual(path, "/loop/b")
        self.assertFalse(func)
        self.assertIn("Redirect loop", capture.output[0])

    def test_redirect_loop_does_not_poison_sibling_cache(self):
        # Regression for the mid-cycle memoization bug: resolving one node of a
        # cycle must not cache a value computed mid-recursion for another node.
        # For /a <-> /b, a fresh top-level url_rewrite reports the *first*
        # redirect target as the rewritten path: url_rewrite("/a") -> "/b" and
        # url_rewrite("/b") -> "/a". When the recursion went through the cached
        # url_rewrite, resolving "/a" first stored the mid-cycle value for "/b"
        # (which returns early on the _visited check) under "/b"'s plain key,
        # so a later url_rewrite("/b") wrongly reported "/b" instead of "/a".
        targets = {"/loop/a": "/loop/b", "/loop/b": "/loop/a"}

        def fake_match(path, method=None):
            raise werkzeug.routing.RequestRedirect("http://x" + targets[path])

        router = MagicMock()
        router.return_value.bind.return_value.match.side_effect = fake_match
        with (
            MockRequest(self.env, mock_router=False),
            patch("odoo.http.root.get_db_router", router),
            self.assertLogs(
                "odoo.addons.http_routing.models.ir_http", level="WARNING"
            ),
        ):
            # Resolve /a first; this is what poisoned /b's cache pre-fix.
            path_a, func_a = self.env["ir.http"].url_rewrite("/loop/a")
            # /b must still report its own fresh result, not a memoized value
            # produced while resolving /a.
            path_b, func_b = self.env["ir.http"].url_rewrite("/loop/b")
        self.assertEqual(path_a, "/loop/b")
        self.assertFalse(func_a)
        self.assertEqual(path_b, "/loop/a")
        self.assertFalse(func_b)
