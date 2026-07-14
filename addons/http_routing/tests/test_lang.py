# Part of Odoo. See LICENSE file for full copyright and licensing details.

from urllib.parse import urlparse

from odoo.tests import HttpCase, TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestNearestLang(TransactionCase):
    """Unit coverage for ``ir.http.get_nearest_lang``.

    In this module (no ``website``) the method is the plain base
    implementation: a pure function of the active frontend languages and the
    requested code, reading only ``self.env`` -- no ``request`` proxy. That
    makes every branch reachable from a ``TransactionCase`` without a live
    frontend request, so pin them down here. Once ``website`` is installed the
    method is overridden to scope languages per-website and does read
    ``request``; that layer is covered by ``website``'s ``test_lang_url``.

    The default install has a single active language (``en_US``), which is
    enough to exercise all four branches: exact hit, prefix hit onto a variant
    (``en_GB`` -> ``en_US``), no match, and the empty-prefix guard.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrHttp = cls.env["ir.http"]
        # Guard the premise: the assertions below assume en_US is the (only
        # relevant) active frontend language.
        active_codes = cls.env["res.lang"]._get_frontend()
        assert "en_US" in active_codes, active_codes

    def test_exact_match_returns_input(self):
        self.assertEqual(self.IrHttp.get_nearest_lang("en_US"), "en_US")

    def test_prefix_match_falls_back_to_variant(self):
        # No en_GB installed, but its short form "en" matches en_US.
        self.assertEqual(self.IrHttp.get_nearest_lang("en_GB"), "en_US")

    def test_bare_short_code_matches_variant(self):
        self.assertEqual(self.IrHttp.get_nearest_lang("en"), "en_US")

    def test_no_matching_language_returns_none(self):
        # A language whose short form matches no active lang.
        self.assertIsNone(self.IrHttp.get_nearest_lang("fr_FR"))

    def test_none_input_returns_none(self):
        self.assertIsNone(self.IrHttp.get_nearest_lang(None))

    def test_empty_input_returns_none(self):
        self.assertIsNone(self.IrHttp.get_nearest_lang(""))

    def test_empty_prefix_returns_none(self):
        # partition("_")[0] is "" for a leading-underscore code; the method must
        # not treat that empty prefix as "matches everything".
        self.assertIsNone(self.IrHttp.get_nearest_lang("_US"))


@tagged("-at_install", "post_install")
class TestLangLadder(HttpCase):
    """End-to-end coverage of the multilang redirect/rewrite ladder in
    ``ir.http._match`` (cases /2../9 + the ``//`` slash-merge) *without*
    ``website`` installed.

    The ladder is the single most intricate and regression-prone piece of this
    module, yet its only integration coverage lived in ``website``
    (``test_lang_url``). That left http_routing un-exercisable in isolation: a
    refactor here got no signal unless ``website`` was also installed and run.

    http_routing ships exactly one ``website=True`` (frontend, multilang)
    route -- ``/website/translations`` -- which is enough to drive the whole
    ladder. Case /8 (bare ``/<lang>/``) redirects *before* re-matching, so it
    needs no homepage route at all. Only case /4 (POST, no-redirect) is omitted
    here: forcing a non-GET frontend hit cleanly would need a dedicated CSRF-
    exempt route, and it stays covered by website's suite.

    Requests are made with ``allow_redirects=False`` so each assertion sees the
    ladder's *own* response (status + Location + Set-Cookie), not the followed
    page.
    """

    #: the sole frontend, multilang endpoint available with only http_routing
    EP = "/website/translations"

    def setUp(self):
        super().setUp()
        # Simulate multi-lang without loading translations, mirroring website's
        # TestLangUrlCommon but driven purely through res.lang / ir.default
        # (there is no ``website`` record to hang languages off here).
        self.lang_fr = self.env["res.lang"]._activate_lang("fr_FR")
        self.lang_fr.url_code = "fr"
        # Pin the frontend default so the ladder's default-lang pivot is
        # deterministic regardless of which langs happen to be active.
        self.env["ir.default"].set("res.partner", "lang", "en_US")
        self.en_code = self.env.ref("base.lang_en").url_code

    def _loc(self, response):
        return urlparse(response.headers.get("Location", "")).path

    # -- served as-is (no redirect) -----------------------------------------

    def test_case_2_no_lang_default_served(self):
        # /2: no lang in URL, default lang requested -> serve as-is.
        r = self.url_open(self.EP, allow_redirects=False)
        self.assertEqual(r.status_code, 200)

    def test_case_3_bot_missing_lang_served(self):
        # /3: a non-default lang is requested (fr cookie) but the user-agent is
        # a bot and the URL has no lang -> serve as-is with the default lang,
        # NOT the redirect a normal browser would get (contrast case /5).
        # NB: pass the cookie via ``cookies=`` (merged into the session jar),
        # never a raw ``Cookie`` header -- the latter clobbers HttpCase's
        # injected ``test_cursor`` cookie and the request is rejected with 400.
        r = self.url_open(
            self.EP,
            allow_redirects=False,
            headers={"User-Agent": "Googlebot/2.1"},
            cookies={"frontend_lang": "fr_FR"},
        )
        self.assertEqual(r.status_code, 200)

    def test_case_9_valid_lang_rewritten_served(self):
        # /9: a valid non-default lang in the URL is stripped by an internal
        # reroute and the request is served (200), not redirected.
        r = self.url_open("/fr" + self.EP, allow_redirects=False)
        self.assertEqual(r.status_code, 200)

    # -- redirects -----------------------------------------------------------

    def test_case_5_missing_lang_redirects_adding_lang(self):
        # /5: non-default lang requested (fr cookie), none in URL -> 303 adding
        # the lang prefix, and the frontend_lang cookie pins the destination.
        r = self.url_open(
            self.EP,
            allow_redirects=False,
            cookies={"frontend_lang": "fr_FR"},
        )
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self._loc(r), "/fr" + self.EP)
        self.assertEqual(r.cookies.get("frontend_lang"), "fr_FR")

    def test_case_5_redirect_preserves_repeated_query_params(self):
        # The ladder forwards request.httprequest.args (a MultiDict) through
        # redirect_query; repeated keys -- e.g. website_sale's
        # ?attrib=1&attrib=2 filters -- must survive the redirect instead of
        # collapsing to the first value.
        r = self.url_open(
            self.EP + "?a=1&a=2&b=3",
            allow_redirects=False,
            cookies={"frontend_lang": "fr_FR"},
        )
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self._loc(r), "/fr" + self.EP)
        self.assertEqual(urlparse(r.headers.get("Location", "")).query, "a=1&a=2&b=3")

    def test_case_6_default_lang_in_url_redirects_stripping_it(self):
        # /6: the default lang sitting in the URL is redirected away (303).
        r = self.url_open("/" + self.en_code + self.EP, allow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self._loc(r), self.EP)

    def test_case_7_lang_alias_redirects_to_url_code(self):
        # /7: the full code (fr_FR) is redirected (301) to its url_code (fr).
        r = self.url_open("/fr_FR" + self.EP, allow_redirects=False)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(self._loc(r), "/fr" + self.EP)

    def test_case_8_homepage_trailing_slash_redirects_with_cookie(self):
        # /8: bare "/<lang>/" -> "/<lang>" (301). This branch redirects before
        # any re-match, so it needs no homepage route. The frontend_lang cookie
        # must record the URL's language (fr_FR), not the default.
        r = self.url_open("/fr/", allow_redirects=False)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(self._loc(r), "/fr")
        self.assertEqual(r.cookies.get("frontend_lang"), "fr_FR")

    def test_double_slash_is_merged(self):
        # Concatenated URLs can yield "//"; the ladder collapses it (301) while
        # preserving the query string.
        r = self.url_open("/website//translations?a=b", allow_redirects=False)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(self._loc(r), self.EP)
        self.assertEqual(urlparse(r.headers.get("Location", "")).query, "a=b")
