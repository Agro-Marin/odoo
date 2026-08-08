# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import MagicMock, Mock, patch

import werkzeug.exceptions
import werkzeug.routing

from odoo.tests import TransactionCase, tagged

from .common import MockRequest, setup_frontend_langs


@tagged("-at_install", "post_install")
class TestUrlCommon(TransactionCase):
    """Shared multi-lang fixture for the URL-generation helpers.

    ``fr_FR`` (url_code ``fr``) is activated next to ``en_US`` (url_code
    ``en``), which is pinned as the frontend default, so every branch of the
    lang insertion/stripping/replacement logic is reachable. Requests use
    ``MockRequest(..., mock_router=False)``, so the helpers match and build
    against the *real* routing map.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        fr = cls.env["res.lang"]._activate_lang("fr_FR")
        fr.url_code = "fr"
        en = cls.env.ref("base.lang_en")
        # Stack-aware: also configures website.language_ids/default_lang_id when
        # ``website`` is installed (see setup_frontend_langs).
        setup_frontend_langs(cls.env, en + fr, en)
        cls.IrHttp = cls.env["ir.http"]
        # /website/translations: the one frontend multilang route available
        # with only http_routing installed (see test_lang.TestLangLadder).
        cls.EP = "/website/translations"


class TestUrlLang(TestUrlCommon):
    """Unit coverage for ``ir.http._url_for`` / ``_url_lang``, which back every
    ``url_for()`` call in frontend QWeb.
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

    def test_never_returns_an_empty_url(self):
        # An empty href resolves against the *current* page, so emitting one
        # silently turns a link home into a self-link. Stripping a bare "/en"
        # produced exactly that: splicing the segment list by hand left
        # ``["" ]`` -> "". Only reachable where "/" is a frontend route (i.e.
        # with ``website`` installed), so assert the invariant rather than the
        # single input, and keep it meaningful on both stacks.
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            for url in ("/en", "/fr", "/", "/en/", "/fr/", self.EP):
                with self.subTest(url=url):
                    self.assertTrue(self.IrHttp._url_for(url).startswith("/"))
                    self.assertTrue(self.IrHttp._url_for(url, "en_US").startswith("/"))
                    self.assertTrue(self.IrHttp._url_for(url, "fr_FR").startswith("/"))

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


class TestUrlLangContext(TestUrlCommon):
    """``_url_lang`` resolves the language from the context, which is not
    guaranteed to hold a usable one: an env built without a lang --
    ``Environment(cr, uid, {})``, or the ``with_context(lang=None)``
    ``website`` itself uses -- must still produce a URL instead of raising and
    taking the whole surrounding render with it.
    """

    def _with_ctx_lang(self, request, value, present=True):
        ctx = dict(request.env.context)
        ctx.pop("lang", None)
        if present:
            ctx["lang"] = value
        request.env = request.env(context=ctx)

    def test_missing_or_falsy_context_lang_does_not_raise(self):
        cases = [("absent", None, False), ("None", None, True), ("False", False, True)]
        for label, value, present in cases:
            with self.subTest(context_lang=label):
                with MockRequest(self.env, mock_router=False) as req:
                    self._with_ctx_lang(req, value, present)
                    # neither KeyError('lang') nor a non-str spliced into the
                    # path ("sequence item 1: expected str, NoneType found")
                    url = self.IrHttp._url_for(self.EP)
                self.assertTrue(url.startswith("/"))
                self.assertNotIn("None", url)
                self.assertNotIn("False", url)

    def test_falsy_context_lang_falls_back_to_request_lang(self):
        with MockRequest(self.env, context={"lang": "fr_FR"}, mock_router=False) as req:
            self._with_ctx_lang(req, None, present=True)
            # request.lang (fr_FR) is the next-best answer, so the URL is
            # localized exactly as it would be with a proper context lang.
            self.assertEqual(self.IrHttp._url_for(self.EP), "/fr" + self.EP)

    def test_lang_placeholder_still_passes_through(self):
        # The fallback must not swallow '[lang]': url_return substitutes it
        # later, so it is deliberately not a known url_code.
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_for(self.EP, "[lang]"), "/[lang]" + self.EP
            )


class TestLangUrlPrefix(TestUrlCommon):
    """``_lang_url_prefix`` is the single place that knows how to glue a
    language code onto a path."""

    def test_prefixes_a_path(self):
        self.assertEqual(self.IrHttp._lang_url_prefix("/shop", "fr"), "/fr/shop")

    def test_root_does_not_gain_a_trailing_slash(self):
        # "/fr/" is exactly what case /8 of the ladder 301s away; emitting it
        # would cost every visitor an extra round trip.
        self.assertEqual(self.IrHttp._lang_url_prefix("/", "fr"), "/fr")

    def test_non_root_relative_path_is_repaired_and_logged(self):
        with self.assertLogs(
            "odoo.addons.http_routing.models.ir_http", level="WARNING"
        ):
            self.assertEqual(self.IrHttp._lang_url_prefix("shop", "fr"), "/fr/shop")

    def test_query_string_is_left_alone(self):
        self.assertEqual(
            self.IrHttp._lang_url_prefix("/shop?a=b", "fr"), "/fr/shop?a=b"
        )


class TestLangUrlUnprefix(TestUrlCommon):
    """``_lang_url_split`` / ``_lang_url_unprefix`` are the inverse of
    ``_lang_url_prefix``, and the only place that decides whether a path's first
    segment is a language."""

    def test_split_reports_the_code_and_the_rest(self):
        with MockRequest(self.env, mock_router=False):
            self.assertEqual(self.IrHttp._lang_url_split("/fr/shop"), ("fr", "/shop"))
            self.assertEqual(self.IrHttp._lang_url_split("/fr"), ("fr", "/"))
            self.assertEqual(self.IrHttp._lang_url_split("/shop"), (None, "/shop"))

    def test_only_url_codes_count_not_full_codes(self):
        # "/fr_FR/..." is case /7's business (a 301 to "/fr/..."), not a prefix
        # to strip here -- otherwise the two disagree about what is a language.
        with MockRequest(self.env, mock_router=False):
            self.assertEqual(
                self.IrHttp._lang_url_split("/fr_FR/shop"), (None, "/fr_FR/shop")
            )

    def test_frontend_url_codes_is_the_single_source(self):
        with MockRequest(self.env, mock_router=False):
            codes = self.env["ir.http"]._frontend_url_codes()
        self.assertIn("fr", codes)
        self.assertIn("en", codes)
        self.assertEqual(
            sorted(codes),
            sorted(lg.url_code for lg in self.env["res.lang"]._get_frontend().values()),
        )

    def test_strips_a_known_url_code(self):
        with MockRequest(self.env, mock_router=False):
            self.assertEqual(self.IrHttp._lang_url_unprefix("/fr/shop"), "/shop")
            self.assertEqual(self.IrHttp._lang_url_unprefix("/en/shop"), "/shop")

    def test_bare_prefix_becomes_root(self):
        # "/fr" and "/fr/" both mean the homepage in fr: round-tripping through
        # _lang_url_prefix must give "/fr" back, not "/fr/fr".
        with MockRequest(self.env, mock_router=False):
            for path in ("/fr", "/fr/"):
                self.assertEqual(self.IrHttp._lang_url_unprefix(path), "/")

    def test_unprefixed_path_untouched(self):
        with MockRequest(self.env, mock_router=False):
            for path in ("/shop", "/", "", "/frites/x", "/fr_FR/shop"):
                self.assertEqual(self.IrHttp._lang_url_unprefix(path), path)

    def test_round_trips_with_prefix(self):
        with MockRequest(self.env, mock_router=False):
            for path in ("/shop", "/"):
                prefixed = self.IrHttp._lang_url_prefix(path, "fr")
                self.assertEqual(self.IrHttp._lang_url_unprefix(prefixed), path)


class TestIsMultilangUrl(TestUrlCommon):
    """Unit coverage for ``ir.http._is_multilang_url`` against real routes."""

    def setUp(self):
        super().setUp()
        # url_rewrite memoizes (routing-map key, path) -> endpoint lookups in
        # the registry-level "routing.rewrites" ormcache; drop this class's
        # probe entries instead of leaking them to the rest of the suite. Dotted
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
    """Unit coverage for ``ir.http._url_localized``: the happy rebuild path and
    every "cannot rebuild -> degrade to the given URL" fallback.

    The contract pinned here is that ``_url_localized`` never raises for a URL
    it cannot rebuild, so no HTTP exception can escape and abort the
    surrounding render.
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

    def test_fragment_is_preserved_not_quoted(self):
        # RFC 3986: the fragment starts at the first "#". Splitting only on "?"
        # left "#top" glued to the path, which then matched no rule and came
        # back percent-quoted -- "/fr/website/translations%23top", a dead link.
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_localized(self.EP + "#top", lang_code="fr_FR"),
                "/fr" + self.EP + "#top",
            )
            self.assertEqual(
                self.IrHttp._url_localized(self.EP + "?a=b#top", lang_code="fr_FR"),
                "/fr" + self.EP + "?a=b#top",
            )
            # a "?" *after* the "#" belongs to the fragment, not to the query
            self.assertEqual(
                self.IrHttp._url_localized(self.EP + "#top?a=b", lang_code="fr_FR"),
                "/fr" + self.EP + "#top?a=b",
            )

    def test_canonical_domain_drops_query_and_fragment(self):
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_localized(
                    self.EP + "?a=b#top",
                    lang_code="fr_FR",
                    canonical_domain="https://example.com",
                ),
                "https://example.com/fr" + self.EP,
            )

    def test_existing_lang_prefix_is_replaced_not_stacked(self):
        # This helper *sets* a URL's language, so it must behave like _url_for
        # and swap an existing prefix rather than stack onto it. Matching a
        # prefixed path finds no rule, so the plain match-then-prefix sequence
        # produced "/fr/fr/...", an URL that 404s.
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_localized("/fr" + self.EP, lang_code="fr_FR"),
                "/fr" + self.EP,
            )
            self.assertEqual(
                self.IrHttp._url_localized("/en" + self.EP, lang_code="fr_FR"),
                "/fr" + self.EP,
            )
            self.assertEqual(
                self.IrHttp._url_localized("/fr" + self.EP, lang_code="en_US"),
                self.EP,
            )
            # ... including on the degradation path, where nothing matches
            self.assertEqual(
                self.IrHttp._url_localized("/fr/no/such/page-4", lang_code="fr_FR"),
                "/fr/no/such/page-4",
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

    def test_non_local_urls_untouched(self):
        # Only a root-relative path has something to localize. Anything else
        # would fall through to the match, fail, and get percent-quoted *as a
        # path* then lang-prefixed -- "https://odoo.com/shop" coming out as
        # "/frhttps%3A//odoo.com/shop". Mirror _url_lang's guard instead.
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            for url in (
                "https://odoo.com" + self.EP,  # absolute
                "//cdn.example.com/x.png",  # protocol-relative
                "mailto:a@b.c",  # non-http scheme
                "tel:+3215",
                "#anchor",  # bare fragment
                "relative/path-1",  # not root-relative
            ):
                self.assertEqual(
                    self.IrHttp._url_localized(url, lang_code="fr_FR"), url
                )

    def test_non_local_url_ignores_canonical_domain(self):
        # An already-absolute URL must not be re-joined onto the canonical
        # domain either.
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            self.assertEqual(
                self.IrHttp._url_localized(
                    "https://odoo.com" + self.EP,
                    lang_code="fr_FR",
                    canonical_domain="https://example.com",
                ),
                "https://odoo.com" + self.EP,
            )

    def test_empty_url_still_falls_back_to_request_path(self):
        # "" and None both mean "localize the current request path"; the
        # non-local guard must not swallow that.
        with MockRequest(
            self.env, path=self.EP, context={"lang": "en_US"}, mock_router=False
        ):
            self.assertEqual(
                self.IrHttp._url_localized("", lang_code="fr_FR"), "/fr" + self.EP
            )
            self.assertEqual(
                self.IrHttp._url_localized(lang_code="fr_FR"), "/fr" + self.EP
            )

    def test_does_not_steer_the_live_request(self):
        # _url_localized must not re-enter ``ir.http._match`` -- the dispatch
        # entry point, which stamps is_frontend/lang and whose lang-ladder case
        # /9 calls ``request.reroute()``, rewriting the URL of the request being
        # served. ``is_frontend=None`` is what makes this discriminate:
        # ``_match`` returns immediately on an already-routed request, so the
        # ladder would never run.
        with MockRequest(
            self.env,
            path="/fr" + self.EP,
            context={"lang": "en_US"},
            mock_router=False,
            is_frontend=None,
        ) as req:
            req.reroute = Mock(side_effect=AssertionError("rerouted the request"))
            before = req.httprequest.path

            self.IrHttp._url_localized("/fr" + self.EP, lang_code="fr_FR")
            self.IrHttp._url_localized(self.EP, lang_code="fr_FR")
            self.IrHttp._url_localized("/no/such/page-4", lang_code="fr_FR")

            req.reroute.assert_not_called()
            self.assertEqual(req.httprequest.path, before)
            self.assertFalse(
                hasattr(req, "is_frontend"),
                "generating a URL must not flag the request as routed",
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


class TestDefaultLang(TestUrlCommon):
    """Unit coverage for ``ir.http._get_default_lang``.

    It is the pivot of the whole lang ladder *and* of every URL built by
    ``_url_lang`` / ``_url_localized``, so it has to be both correct for a
    stale configuration and cheap enough to call once per generated link.
    """

    def test_stale_default_falls_back_to_an_active_lang(self):
        # ``ir.default`` may name a language that is not (or no longer) active
        # -- nothing validates the value, and a data file, an upgrade or an
        # archived language can leave one behind. ``_get_data`` answers those
        # with a dummy LangData whose every field is ``False``.
        self.env["ir.default"].set("res.partner", "lang", "xx_XX")
        with MockRequest(self.env, context={"lang": "fr_FR"}, mock_router=False):
            default = self.IrHttp._get_default_lang()
            self.assertTrue(default, "must not return the falsy dummy LangData")
            self.assertIn(default.code, self.env["res.lang"]._get_frontend())
            self.assertTrue(default.url_code)

    def test_stale_default_does_not_invert_canonical_urls(self):
        # The dummy LangData is never equal to a real language, so pivoting the
        # ladder on it inverts the site's canonical URLs: the default language
        # loses its prefix-free form. Pin the URL-building half here (the
        # request-routing half is TestLangLadder.test_stale_default_*).
        self.env["ir.default"].set("res.partner", "lang", "xx_XX")
        with MockRequest(self.env, context={"lang": "en_US"}, mock_router=False):
            # en_US is the fallback default => its URLs stay unprefixed ...
            self.assertEqual(
                self.IrHttp._url_localized(self.EP, lang_code="en_US"), self.EP
            )
            self.assertEqual(self.IrHttp._url_for(self.EP), self.EP)
            # ... while a non-default language still gets its prefix.
            self.assertEqual(
                self.IrHttp._url_localized(self.EP, lang_code="fr_FR"),
                "/fr" + self.EP,
            )

    def test_default_lang_is_not_queried_per_call(self):
        # ``ir.default._get`` runs a ``search`` on ir_default and is not
        # memoized; _get_default_lang sits on the URL-building hot path (once
        # per url_for() on a multilingual page), so it must not pay that query.
        with MockRequest(self.env, context={"lang": "fr_FR"}, mock_router=False):
            self.IrHttp._get_default_lang()  # warm
            self.env.flush_all()
            before = self.cr.sql_log_count
            for _ in range(10):
                self.IrHttp._get_default_lang()
            self.assertEqual(self.cr.sql_log_count - before, 0)

    def test_default_lang_cache_is_invalidated(self):
        # Assert on ``_get_default_lang_code`` -- the ormcached lookup this
        # covers -- rather than on ``_get_default_lang``: ``website`` overrides
        # the latter to read ``website.default_lang_id`` and never consults
        # ``ir.default`` at all, so asserting there would pass only on the
        # http_routing-only stack and silently test nothing elsewhere.
        self.assertEqual(self.IrHttp._get_default_lang_code(), "en_US")
        self.env["ir.default"].set("res.partner", "lang", "fr_FR")
        self.assertEqual(
            self.IrHttp._get_default_lang_code(),
            "fr_FR",
            "ir.default writes must drop the ormcache (they clear_cache())",
        )
        self.env["res.lang"]._activate_lang("nl_NL")
        self.assertEqual(
            self.IrHttp._get_default_lang_code(),
            "fr_FR",
            "res.lang writes clear_cache('stable'), which cascades to 'default'",
        )


class TestUrlRewrite(TestUrlCommon):
    """Unit coverage for ``ir.http.url_rewrite`` edge cases."""

    def setUp(self):
        super().setUp()
        # Drop this class's probe entries from the registry-level
        # "routing.rewrites" ormcache (same rationale as TestIsMultilangUrl).
        self.addCleanup(self.registry.clear_cache, "routing")

    def test_method_not_allowed_reports_unrouted(self):
        # url_rewrite probes with POST then GET. A rule that accepts neither
        # (e.g. ``methods=['PUT']``) makes the second probe raise
        # MethodNotAllowed too: "no endpoint we can name" must degrade to
        # (path, False) rather than escape and 500 the callers in website /
        # website_sale, neither of which guards this call.
        router = MagicMock()
        router.return_value.bind.return_value.match.side_effect = (
            werkzeug.exceptions.MethodNotAllowed()
        )
        with (
            MockRequest(self.env, mock_router=False),
            patch("odoo.http.root.get_db_router", router),
        ):
            self.assertEqual(
                self.env["ir.http"].url_rewrite("/put/only"), ("/put/only", False)
            )

    def test_works_without_a_request(self):
        # url_rewrite is an @api.model method whose cache lives on the registry,
        # so the database is the env's by construction: reading ``request.db``
        # instead would couple a pure routing lookup to there being a request,
        # making it unusable from cron, RPC or a plain model method.
        self.assertEqual(
            self.env["ir.http"].url_rewrite(self.EP)[0],
            self.EP,
        )

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
        # Resolving one node of a cycle must not cache a value computed
        # mid-recursion for another node: a fresh top-level url_rewrite reports
        # the *first* redirect target, so url_rewrite("/a") -> "/b" and
        # url_rewrite("/b") -> "/a". Recursing through the cached url_rewrite
        # stored "/b"'s early _visited return under its plain key instead.
        targets = {"/loop/a": "/loop/b", "/loop/b": "/loop/a"}

        def fake_match(path, method=None):
            raise werkzeug.routing.RequestRedirect("http://x" + targets[path])

        router = MagicMock()
        router.return_value.bind.return_value.match.side_effect = fake_match
        with (
            MockRequest(self.env, mock_router=False),
            patch("odoo.http.root.get_db_router", router),
            self.assertLogs("odoo.addons.http_routing.models.ir_http", level="WARNING"),
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


class TestIsMultilangUrlWithoutRequest(TestUrlCommon):
    """``_is_multilang_url`` answers from ``self.env``.

    It delegates its routing probe to ``url_rewrite``, which is already
    request-free; keeping the wrapper bound to ``request`` made the whole
    question unaskable from a sitemap builder, a cron or a plain model method.
    """

    def setUp(self):
        super().setUp()
        self.addCleanup(self.registry.clear_cache, "routing")

    def test_works_without_a_request(self):
        self.assertTrue(self.IrHttp._is_multilang_url(self.EP))
        self.assertFalse(self.IrHttp._is_multilang_url("/web/login"))
        self.assertFalse(self.IrHttp._is_multilang_url("/foo/static/x.js"))

    def test_lang_prefix_still_ignored_without_a_request(self):
        self.assertTrue(self.IrHttp._is_multilang_url("/fr" + self.EP))
