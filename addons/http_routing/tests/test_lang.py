# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import Mock
from urllib.parse import urlparse

from werkzeug.exceptions import HTTPException

from odoo.tests import HttpCase, TransactionCase, tagged

from .common import MockRequest, setup_frontend_langs


@tagged("-at_install", "post_install")
class TestNearestLang(TransactionCase):
    """Unit coverage for ``ir.http.get_nearest_lang``.

    Without ``website`` this is the plain base implementation: a pure function
    of the active frontend languages and the requested code, so every branch is
    reachable from a ``TransactionCase``. Website's override (which scopes
    languages per-website and reads ``request``) is covered by its own
    ``test_lang_url``.
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
        # en_GB is not installed, but its base language "en" matches en_US.
        self.assertEqual(self.IrHttp.get_nearest_lang("en_GB"), "en_US")

    def test_bare_short_code_matches_variant(self):
        self.assertEqual(self.IrHttp.get_nearest_lang("en"), "en_US")

    def test_no_matching_language_returns_none(self):
        # A language whose base language matches no active lang.
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
        # kab (Kabyle) is not a variant of ka (Georgian): matching compares the
        # base language exactly, not by string prefix, which would route
        # Georgian visitors onto Kabyle.
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
class TestRedirectLang(TransactionCase):
    """``_redirect_lang`` is the single exit every 3xx of the ladder takes.

    Unit-level, because what it has to get right is mechanical -- the status,
    the Location, the query string it carries and the ``frontend_lang`` cookie
    it pins -- and pinning that through ``HttpCase`` costs a server round trip
    per case. ``TestLangLadder`` below still drives the whole ladder end to end;
    this covers the exit itself, including combinations no route reachable with
    only ``http_routing`` installed can produce.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        fr = cls.env["res.lang"]._activate_lang("fr_FR")
        fr.url_code = "fr"
        setup_frontend_langs(
            cls.env, cls.env.ref("base.lang_en") + fr, cls.env.ref("base.lang_en")
        )
        cls.IrHttp = cls.env["ir.http"]

    def _redirect(self, target, code=303, path="/x", lang="fr_FR"):
        with MockRequest(
            self.env, path=path, context={"lang": lang}, mock_router=False
        ):
            with self.assertRaises(HTTPException) as caught:
                self.IrHttp._redirect_lang(target, code=code)
        return caught.exception.response

    def test_status_and_location(self):
        response = self._redirect("/fr/shop")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(urlparse(response.headers["Location"]).path, "/fr/shop")

    def test_permanent_moves_keep_their_code(self):
        self.assertEqual(self._redirect("/fr", code=301).status_code, 301)

    def test_cookie_pins_the_destination_language(self):
        # The cookie must record ``request.lang`` -- the same value
        # ``_frontend_pre_dispatch`` writes on the request finally dispatched --
        # or the followed request disagrees with the redirect and bounces back.
        response = self._redirect("/fr/shop", lang="fr_FR")
        self.assertIn("frontend_lang=fr_FR", response.headers["Set-Cookie"])

    def test_repeated_query_params_survive(self):
        # website_sale's ?attrib=1&attrib=2 filters must not collapse to the
        # first value on the way through the redirect.
        response = self._redirect("/fr/shop", path="/shop?attrib=1&attrib=2&b=3")
        self.assertEqual(
            urlparse(response.headers["Location"]).query, "attrib=1&attrib=2&b=3"
        )

    def test_query_is_appended_before_the_fragment(self):
        # RFC 3986 order: a query spliced after the fragment is part of the
        # fragment and never reaches the server.
        response = self._redirect("/fr/shop#top", path="/shop?a=b")
        location = urlparse(response.headers["Location"])
        self.assertEqual(location.query, "a=b")
        self.assertEqual(location.fragment, "top")

    def test_existing_query_on_the_target_is_kept(self):
        response = self._redirect("/fr/shop?keep=1", path="/shop?a=b")
        self.assertEqual(urlparse(response.headers["Location"]).query, "keep=1&a=b")


@tagged("-at_install", "post_install")
class TestRerouteLadder(TransactionCase):
    """``_reroute_for_lang`` -- cases /2../9 of :meth:`ir.http._match` -- as a
    table.

    ``TestLangLadder`` drives the same ladder end to end and is the proof that
    it is wired into dispatch; it also costs a server round trip per case and
    can only reach the combinations some *route* makes reachable. This asserts
    the decision itself, so every branch (including the ones that need a bot
    User-Agent, or a POST, or a language the site does not serve) is one cheap
    call, and the ladder reads as what it is: a table of (URL shape, requested
    language, may-redirect) -> (serve | redirect | rewrite).
    """

    BOT = "Mozilla/5.0 (compatible; Googlebot/2.1)"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        fr = cls.env["res.lang"]._activate_lang("fr_FR")
        fr.url_code = "fr"
        cls.en = cls.env.ref("base.lang_en")
        setup_frontend_langs(cls.env, cls.en + fr, cls.en)
        cls.IrHttp = cls.env["ir.http"]

    def _run(self, path, path_no_lang, url_lang_str, lang, allow_redirect=True, ua=""):
        """Apply the ladder; return ``("serve", path)``, ``("rewrite", path)``
        or ``("redirect", code, location)``.
        """
        default = self.env["ir.http"]._get_default_lang()
        with MockRequest(
            self.env,
            path=path,
            context={"lang": lang},
            user_agent=ua,
            mock_router=False,
        ) as request:
            request.reroute = Mock()
            try:
                result = self.IrHttp._reroute_for_lang(
                    path, path_no_lang, url_lang_str, default, allow_redirect
                )
            except HTTPException as caught:
                response = caught.response
                return ("redirect", response.status_code, response.headers["Location"])
            if request.reroute.called:
                return ("rewrite", result)
            return ("serve", result)

    # -- served as-is --------------------------------------------------------

    def test_case_2_no_lang_and_default_requested(self):
        self.assertEqual(self._run("/shop", "/shop", None, "en_US"), ("serve", "/shop"))

    def test_case_3_bot_gets_the_default_lang_not_a_redirect(self):
        # A crawler must not be bounced to /fr just because it would have been
        # served French: it indexes the URL it asked for.
        self.assertEqual(
            self._run("/shop", "/shop", None, "fr_FR", ua=self.BOT), ("serve", "/shop")
        )

    def test_case_4_unsafe_method_is_never_redirected(self):
        # RFC 9110 lets a client replay a 3xx on an unsafe method as GET, which
        # drops the body; ``allow_redirect`` is how the caller says so.
        self.assertEqual(
            self._run("/shop", "/shop", None, "fr_FR", allow_redirect=False),
            ("serve", "/shop"),
        )

    # -- redirects -----------------------------------------------------------

    def test_case_5_missing_lang_is_inserted(self):
        kind, code, location = self._run("/shop", "/shop", None, "fr_FR")
        self.assertEqual((kind, code), ("redirect", 303))
        self.assertEqual(urlparse(location).path, "/fr/shop")

    def test_case_5_on_the_homepage_does_not_emit_a_trailing_slash(self):
        # "/" would give "/<lang>/", which case /8 then 301s away: one wasted
        # round trip on the most requested URL of the site.
        _kind, _code, location = self._run("/", "/", None, "fr_FR")
        self.assertEqual(urlparse(location).path, "/fr")

    def test_case_6_default_lang_prefix_is_stripped(self):
        kind, code, location = self._run("/en/shop", "/shop", "en", "en_US")
        self.assertEqual((kind, code), ("redirect", 303))
        self.assertEqual(urlparse(location).path, "/shop")

    def test_case_7_alias_redirects_permanently_to_the_url_code(self):
        # /fr_FR/... is a recognized spelling but not the canonical one.
        kind, code, location = self._run("/fr_FR/shop", "/shop", "fr_FR", "fr_FR")
        self.assertEqual((kind, code), ("redirect", 301))
        self.assertEqual(urlparse(location).path, "/fr/shop")

    def test_case_7_bare_alias_does_not_emit_a_trailing_slash(self):
        _kind, _code, location = self._run("/fr_FR", "/", "fr_FR", "fr_FR")
        self.assertEqual(urlparse(location).path, "/fr")

    def test_case_8_homepage_trailing_slash(self):
        kind, code, location = self._run("/fr/", "/", "fr", "fr_FR")
        self.assertEqual((kind, code), ("redirect", 301))
        self.assertEqual(urlparse(location).path, "/fr")

    # -- rewritten (served in the URL's language) ----------------------------

    def test_case_9_valid_lang_is_stripped_and_served(self):
        self.assertEqual(
            self._run("/fr/shop", "/shop", "fr", "fr_FR"), ("rewrite", "/shop")
        )

    def test_case_9_catches_the_aliases_when_redirecting_is_forbidden(self):
        # This is what makes ``POST /fr_FR/x`` and ``POST /en/x`` reach dispatch
        # instead of 404ing on a prefix nothing would strip: cases /6 and /7
        # both need ``allow_redirect``.
        for path_prefix, url_lang, lang in (
            ("/fr_FR", "fr_FR", "fr_FR"),
            ("/en", "en", "en_US"),
        ):
            with self.subTest(prefix=path_prefix):
                self.assertEqual(
                    self._run(
                        path_prefix + "/shop",
                        "/shop",
                        url_lang,
                        lang,
                        allow_redirect=False,
                    ),
                    ("rewrite", "/shop"),
                )

    def test_every_case_is_decided(self):
        # The ladder ends on a "couldn't route this" warning that is meant to be
        # unreachable. Sweep the input space it is defined over and assert none
        # of it lands there -- if a future branch reordering opens a hole, this
        # says so instead of a visitor getting the URL served raw.
        logger = "odoo.addons.http_routing.models.ir_http"
        for path, path_no_lang, url_lang in (
            ("/shop", "/shop", None),
            ("/fr/shop", "/shop", "fr"),
            ("/en/shop", "/shop", "en"),
            ("/fr_FR/shop", "/shop", "fr_FR"),
            ("/fr/", "/", "fr"),
            ("/en/", "/", "en"),
            ("/fr", "/", "fr"),
            ("/", "/", None),
        ):
            for lang in ("en_US", "fr_FR"):
                for allow in (True, False):
                    for ua in ("", self.BOT):
                        with self.subTest(
                            path=path, lang=lang, allow=allow, bot=bool(ua)
                        ):
                            with self.assertNoLogs(logger, level="WARNING"):
                                self._run(
                                    path,
                                    path_no_lang,
                                    url_lang,
                                    lang,
                                    allow_redirect=allow,
                                    ua=ua,
                                )


@tagged("-at_install", "post_install")
class TestLangLadder(HttpCase):
    """End-to-end coverage of the multilang redirect/rewrite ladder in
    ``ir.http._match`` (cases /2../9 + the ``//`` slash-merge) *without*
    ``website`` installed.

    ``/website/translations`` -- the sole ``website=True`` (frontend,
    multilang) route this module ships -- drives the whole ladder. Requests use
    ``allow_redirects=False`` so each assertion sees the ladder's *own*
    response (status + Location + Set-Cookie), not the followed page.
    """

    #: the sole frontend, multilang endpoint available with only http_routing
    EP = "/website/translations"

    def setUp(self):
        super().setUp()
        # Simulate multi-lang without loading translations, mirroring website's
        # TestLangUrlCommon.
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
        # replace("//", "/") would turn "///" into "//" and chain a second
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
        # drops the body and the method.
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                r = self._open(self.EP, method)  # case /2: no cookie, default lang
                self.assertEqual(r.status_code, 400, "must reach dispatch, not 3xx")

    def test_unsafe_methods_not_redirected_with_lang_cookie(self):
        # Case /4: no lang in the URL, a non-default one requested by cookie,
        # redirecting forbidden. A guard excluding POST only let
        # PUT/PATCH/DELETE fall to case /5 and 303 to the lang-prefixed URL,
        # dropping the body.
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
        # An ``ir.default`` naming an inactive language must not invert the
        # site's canonical URLs: _get_default_lang falls back to an active
        # language, so case /2 keeps serving the prefix-free URL and case /6
        # keeps stripping the prefix. Verified end to end because it is a
        # routing symptom, not a helper return value.
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
