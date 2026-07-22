# Part of Odoo. See LICENSE file for full copyright and licensing details.

from urllib.parse import urlparse

from odoo.tests import HttpCase, TransactionCase, tagged

from .common import setup_frontend_langs


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

    def test_base_lang_no_false_prefix_match(self):
        # kab (Kabyle) is not a variant of ka (Georgian): matching must
        # compare the base language exactly, not by string prefix, which used
        # to route Georgian visitors onto Kabyle.
        self.env["res.lang"]._activate_lang("kab_DZ")
        self.assertEqual(self.IrHttp.get_nearest_lang("kab"), "kab_DZ")
        self.assertEqual(self.IrHttp.get_nearest_lang("kab_XX"), "kab_DZ")
        self.assertIsNone(self.IrHttp.get_nearest_lang("ka_GE"))
        self.assertIsNone(self.IrHttp.get_nearest_lang("ka"))

    def test_script_variant_matches_base_lang(self):
        # sr@latin carries its qualifier with "@" instead of "_": both
        # directions must still resolve to the base language "sr".
        self.env["res.lang"]._activate_lang("sr@latin")
        self.assertEqual(self.IrHttp.get_nearest_lang("sr_RS"), "sr@latin")
        self.assertEqual(self.IrHttp.get_nearest_lang("sr"), "sr@latin")


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
        lang_en = self.env.ref("base.lang_en")
        # Pin the frontend languages and default so the ladder's default-lang
        # pivot is deterministic, on whichever stack is installed.
        setup_frontend_langs(self.env, lang_en + self.lang_fr, lang_en)
        self.en_code = lang_en.url_code

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

    def test_direct_match_matches_only_once(self):
        # A directly-matched frontend URL (case /2) must not be matched a
        # second time after the ladder: the rule found by the first match is
        # reused. Pin it by counting _match_and_flag calls for one request.
        IrHttp = self.registry["ir.http"]
        matcher = IrHttp._match_and_flag  # bound classmethod
        calls = []

        def counting(path):
            calls.append(path)
            return matcher(path)

        self.patch(IrHttp, "_match_and_flag", counting)
        r = self.url_open(self.EP, allow_redirects=False)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(calls, [self.EP])

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

    def test_case_7_bare_lang_alias_redirects_without_trailing_slash(self):
        # /7 on a bare "/fr_FR": redirect straight to "/fr", not to "/fr/"
        # which case /8 would then 301 a second time.
        r = self.url_open("/fr_FR", allow_redirects=False)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(self._loc(r), "/fr")

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

    def test_slash_runs_merge_in_one_redirect(self):
        # Any run of slashes collapses in a single hop; a pairwise
        # replace("//", "/") used to turn "///" into "//" and chain a second
        # redirect.
        r = self.url_open("/website///translations", allow_redirects=False)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(self._loc(r), self.EP)

    # -- unsafe methods ------------------------------------------------------
    #
    # ``EP`` is a csrf-protected ``type='http'`` route, so a non-GET hit that
    # *reaches dispatch* answers 400 (csrf) while one the ladder mishandles
    # answers 404 or a 3xx. That makes the status a clean three-way probe:
    #   400 -> routed and served   3xx -> redirected   404 -> lost
    #
    # A browser User-Agent is required throughout: ``is_a_bot()`` substring-
    # matches "curl"/"bot"/... and the default test opener's UA would take
    # case /3 instead of the branch under test.
    BROWSER_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120"}

    def _open(self, url, method):
        return self.url_open(
            url, method=method, allow_redirects=False, headers=self.BROWSER_UA
        )

    def test_unsafe_methods_are_never_redirected(self):
        # RFC 9110: a client may replay a 301/302 on an unsafe method as GET,
        # and a 303 *must* be replayed as GET -- so a redirect here silently
        # drops the body and the method. The guard used to exclude POST only,
        # so PUT/PATCH/DELETE got a 303 to the lang-prefixed URL (case /5) and
        # the write never happened.
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                r = self._open(self.EP, method)  # case /5 without the cookie
                self.assertEqual(r.status_code, 400, "must reach dispatch, not 3xx")

    def test_unsafe_methods_not_redirected_with_lang_cookie(self):
        # Same, driven through case /5 proper: a non-default lang is requested
        # by cookie while the URL carries none.
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                r = self.url_open(
                    self.EP,
                    method=method,
                    allow_redirects=False,
                    headers=self.BROWSER_UA,
                    cookies={"frontend_lang": "fr_FR"},
                )
                self.assertEqual(r.status_code, 400)

    def test_cors_preflight_is_not_redirected(self):
        # A browser never follows a redirect on a CORS preflight, so a 3xx
        # here fails the preflight rather than answering it. OPTIONS is safe
        # per SAFE_HTTP_METHODS yet must not be redirected either.
        r = self.url_open(
            self.EP,
            method="OPTIONS",
            allow_redirects=False,
            headers=self.BROWSER_UA,
            cookies={"frontend_lang": "fr_FR"},
        )
        self.assertNotIn(r.status_code, (301, 302, 303, 307, 308))

    def test_unsafe_method_on_lang_alias_is_served(self):
        # A recognized-but-non-canonical lang prefix (fr_FR for url_code "fr",
        # en_US for "en") hit no ladder branch when redirecting was forbidden:
        # the path kept its prefix, fell to the "couldn't correctly route"
        # warning and 404'd -- while the same URL 301'd for GET. Strip the
        # prefix and serve instead.
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            for prefix in ("/fr_FR", "/en_US"):
                with self.subTest(method=method, prefix=prefix):
                    r = self._open(prefix + self.EP, method)
                    self.assertEqual(r.status_code, 400, "must reach dispatch, not 404")

    def test_unsafe_method_on_canonical_lang_is_served(self):
        # Regression guard for the pre-existing case /9 behaviour.
        for method in ("POST", "PUT", "DELETE"):
            for prefix in ("/fr", "/en"):
                with self.subTest(method=method, prefix=prefix):
                    r = self._open(prefix + self.EP, method)
                    self.assertEqual(r.status_code, 400)

    def test_unsafe_method_slash_run_is_not_merged(self):
        # The slash-merge is a redirect too, so it is off for unsafe methods --
        # as it already was for POST. A clean 404 beats a 301 the client
        # replays as a GET, silently dropping the body.
        for method in ("POST", "PUT", "DELETE"):
            with self.subTest(method=method):
                r = self._open("/website//translations", method)
                self.assertEqual(r.status_code, 404)

    def test_stale_default_lang_keeps_canonical_urls(self):
        # An ``ir.default`` naming an inactive language makes _get_default_lang
        # answer a dummy LangData that equals no real language. The ladder then
        # inverts the site's canonical URLs: case /2 stops recognizing the
        # default and bounces "/EP" to "/en/EP", and case /6 stops stripping the
        # prefix, so the prefixed form becomes canonical. Verified end to end
        # because it is a routing symptom, not a helper return value.
        self.env["ir.default"].set("res.partner", "lang", "xx_XX")
        self.env.flush_all()
        self.env.registry.clear_cache()

        served = self._open(self.EP, "GET")
        self.assertEqual(served.status_code, 200, "default lang must stay prefix-free")

        stripped = self._open("/" + self.en_code + self.EP, "GET")
        self.assertEqual(stripped.status_code, 303)
        self.assertEqual(self._loc(stripped), self.EP)

    def test_safe_methods_still_redirect(self):
        # The narrower guard must not stop GET/HEAD canonicalization.
        for method in ("GET", "HEAD"):
            with self.subTest(method=method):
                r = self._open("/fr_FR" + self.EP, method)
                self.assertEqual(r.status_code, 301)
                self.assertEqual(self._loc(r), "/fr" + self.EP)
