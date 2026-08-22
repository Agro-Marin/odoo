from unittest.mock import Mock
from urllib.parse import urlparse

from werkzeug.exceptions import HTTPException

from odoo.tests import HttpCase, TransactionCase, tagged

from .common import MockRequest, setup_frontend_langs


@tagged("-at_install", "post_install")
class TestNearestLang(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrHttp = cls.env["ir.http"]
        active_codes = cls.env["res.lang"]._get_frontend()
        assert "en_US" in active_codes, active_codes

    def test_exact_match_returns_input(self):
        self.assertEqual(self.IrHttp.get_nearest_lang("en_US"), "en_US")

    def test_prefix_match_falls_back_to_variant(self):
        self.assertEqual(self.IrHttp.get_nearest_lang("en_GB"), "en_US")

    def test_bare_short_code_matches_variant(self):
        self.assertEqual(self.IrHttp.get_nearest_lang("en"), "en_US")

    def test_no_matching_language_returns_none(self):
        self.assertIsNone(self.IrHttp.get_nearest_lang("fr_FR"))

    def test_none_input_returns_none(self):
        self.assertIsNone(self.IrHttp.get_nearest_lang(None))

    def test_empty_input_returns_none(self):
        self.assertIsNone(self.IrHttp.get_nearest_lang(""))

    def test_empty_prefix_returns_none(self):
        self.assertIsNone(self.IrHttp.get_nearest_lang("_US"))

    def test_base_lang_no_false_prefix_match(self):
        self.env["res.lang"]._activate_lang("kab_DZ")
        self.assertEqual(self.IrHttp.get_nearest_lang("kab"), "kab_DZ")
        self.assertEqual(self.IrHttp.get_nearest_lang("kab_XX"), "kab_DZ")
        self.assertIsNone(self.IrHttp.get_nearest_lang("ka_GE"))
        self.assertIsNone(self.IrHttp.get_nearest_lang("ka"))

    def test_script_variant_matches_base_lang(self):
        self.env["res.lang"]._activate_lang("sr@latin")
        self.assertEqual(self.IrHttp.get_nearest_lang("sr_RS"), "sr@latin")
        self.assertEqual(self.IrHttp.get_nearest_lang("sr"), "sr@latin")


@tagged("-at_install", "post_install")
class TestRedirectLang(TransactionCase):
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
        response = self._redirect("/fr/shop", lang="fr_FR")
        self.assertIn("frontend_lang=fr_FR", response.headers["Set-Cookie"])

    def test_repeated_query_params_survive(self):
        response = self._redirect("/fr/shop", path="/shop?attrib=1&attrib=2&b=3")
        self.assertEqual(
            urlparse(response.headers["Location"]).query, "attrib=1&attrib=2&b=3"
        )

    def test_query_is_appended_before_the_fragment(self):
        response = self._redirect("/fr/shop#top", path="/shop?a=b")
        location = urlparse(response.headers["Location"])
        self.assertEqual(location.query, "a=b")
        self.assertEqual(location.fragment, "top")

    def test_existing_query_on_the_target_is_kept(self):
        response = self._redirect("/fr/shop?keep=1", path="/shop?a=b")
        self.assertEqual(urlparse(response.headers["Location"]).query, "keep=1&a=b")


@tagged("-at_install", "post_install")
class TestRerouteLadder(TransactionCase):
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

    def test_case_2_no_lang_and_default_requested(self):
        self.assertEqual(self._run("/shop", "/shop", None, "en_US"), ("serve", "/shop"))

    def test_case_3_bot_gets_the_default_lang_not_a_redirect(self):
        self.assertEqual(
            self._run("/shop", "/shop", None, "fr_FR", ua=self.BOT), ("serve", "/shop")
        )

    def test_case_4_unsafe_method_is_never_redirected(self):
        self.assertEqual(
            self._run("/shop", "/shop", None, "fr_FR", allow_redirect=False),
            ("serve", "/shop"),
        )

    def test_case_5_missing_lang_is_inserted(self):
        kind, code, location = self._run("/shop", "/shop", None, "fr_FR")
        self.assertEqual((kind, code), ("redirect", 303))
        self.assertEqual(urlparse(location).path, "/fr/shop")

    def test_case_5_on_the_homepage_does_not_emit_a_trailing_slash(self):
        _kind, _code, location = self._run("/", "/", None, "fr_FR")
        self.assertEqual(urlparse(location).path, "/fr")

    def test_case_6_default_lang_prefix_is_stripped(self):
        kind, code, location = self._run("/en/shop", "/shop", "en", "en_US")
        self.assertEqual((kind, code), ("redirect", 303))
        self.assertEqual(urlparse(location).path, "/shop")

    def test_case_7_alias_redirects_permanently_to_the_url_code(self):
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

    def test_case_9_valid_lang_is_stripped_and_served(self):
        self.assertEqual(
            self._run("/fr/shop", "/shop", "fr", "fr_FR"), ("rewrite", "/shop")
        )

    def test_case_9_catches_the_aliases_when_redirecting_is_forbidden(self):
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
    EP = "/website/translations"

    def setUp(self):
        super().setUp()
        self.lang_fr = self.env["res.lang"]._activate_lang("fr_FR")
        self.lang_fr.url_code = "fr"
        lang_en = self.env.ref("base.lang_en")
        setup_frontend_langs(self.env, lang_en + self.lang_fr, lang_en)
        self.en_code = lang_en.url_code

    def _loc(self, response):
        return urlparse(response.headers.get("Location", "")).path

    def test_case_2_no_lang_default_served(self):
        r = self.url_open(self.EP, allow_redirects=False)
        self.assertEqual(r.status_code, 200)

    def test_case_3_bot_missing_lang_served(self):
        r = self.url_open(
            self.EP,
            allow_redirects=False,
            headers={"User-Agent": "Googlebot/2.1"},
            cookies={"frontend_lang": "fr_FR"},
        )
        self.assertEqual(r.status_code, 200)

    def test_case_9_valid_lang_rewritten_served(self):
        r = self.url_open("/fr" + self.EP, allow_redirects=False)
        self.assertEqual(r.status_code, 200)

    def test_direct_match_matches_only_once(self):
        IrHttp = self.registry["ir.http"]
        matcher = IrHttp._match_and_flag
        calls = []

        def counting(path):
            calls.append(path)
            return matcher(path)

        self.patch(IrHttp, "_match_and_flag", counting)
        r = self.url_open(self.EP, allow_redirects=False)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(calls, [self.EP])

    def test_case_5_missing_lang_redirects_adding_lang(self):
        r = self.url_open(
            self.EP,
            allow_redirects=False,
            cookies={"frontend_lang": "fr_FR"},
        )
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self._loc(r), "/fr" + self.EP)
        self.assertEqual(r.cookies.get("frontend_lang"), "fr_FR")

    def test_case_5_redirect_preserves_repeated_query_params(self):
        r = self.url_open(
            self.EP + "?a=1&a=2&b=3",
            allow_redirects=False,
            cookies={"frontend_lang": "fr_FR"},
        )
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self._loc(r), "/fr" + self.EP)
        self.assertEqual(urlparse(r.headers.get("Location", "")).query, "a=1&a=2&b=3")

    def test_case_6_default_lang_in_url_redirects_stripping_it(self):
        r = self.url_open("/" + self.en_code + self.EP, allow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self._loc(r), self.EP)

    def test_case_7_lang_alias_redirects_to_url_code(self):
        r = self.url_open("/fr_FR" + self.EP, allow_redirects=False)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(self._loc(r), "/fr" + self.EP)

    def test_case_7_bare_lang_alias_redirects_without_trailing_slash(self):
        r = self.url_open("/fr_FR", allow_redirects=False)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(self._loc(r), "/fr")

    def test_case_8_homepage_trailing_slash_redirects_with_cookie(self):
        r = self.url_open("/fr/", allow_redirects=False)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(self._loc(r), "/fr")
        self.assertEqual(r.cookies.get("frontend_lang"), "fr_FR")

    def test_double_slash_is_merged(self):
        r = self.url_open("/website//translations?a=b", allow_redirects=False)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(self._loc(r), self.EP)
        self.assertEqual(urlparse(r.headers.get("Location", "")).query, "a=b")

    def test_slash_runs_merge_in_one_redirect(self):
        r = self.url_open("/website///translations", allow_redirects=False)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(self._loc(r), self.EP)

    BROWSER_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120"}

    def _open(self, url, method):
        return self.url_open(
            url, method=method, allow_redirects=False, headers=self.BROWSER_UA
        )

    def test_unsafe_methods_are_never_redirected(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                r = self._open(self.EP, method)
                self.assertEqual(r.status_code, 400, "must reach dispatch, not 3xx")

    def test_unsafe_methods_not_redirected_with_lang_cookie(self):
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
        r = self.url_open(
            self.EP,
            method="OPTIONS",
            allow_redirects=False,
            headers=self.BROWSER_UA,
            cookies={"frontend_lang": "fr_FR"},
        )
        self.assertNotIn(r.status_code, (301, 302, 303, 307, 308))

    def test_unsafe_method_on_lang_alias_is_served(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            for prefix in ("/fr_FR", "/en_US"):
                with self.subTest(method=method, prefix=prefix):
                    r = self._open(prefix + self.EP, method)
                    self.assertEqual(r.status_code, 400, "must reach dispatch, not 404")

    def test_unsafe_method_on_canonical_lang_is_served(self):
        for method in ("POST", "PUT", "DELETE"):
            for prefix in ("/fr", "/en"):
                with self.subTest(method=method, prefix=prefix):
                    r = self._open(prefix + self.EP, method)
                    self.assertEqual(r.status_code, 400)

    def test_unsafe_method_slash_run_is_not_merged(self):
        for method in ("POST", "PUT", "DELETE"):
            with self.subTest(method=method):
                r = self._open("/website//translations", method)
                self.assertEqual(r.status_code, 404)

    def test_stale_default_lang_keeps_canonical_urls(self):
        self.env["ir.default"].set("res.partner", "lang", "xx_XX")
        self.env.flush_all()
        self.env.registry.clear_cache()

        served = self._open(self.EP, "GET")
        self.assertEqual(served.status_code, 200, "default lang must stay prefix-free")

        stripped = self._open("/" + self.en_code + self.EP, "GET")
        self.assertEqual(stripped.status_code, 303)
        self.assertEqual(self._loc(stripped), self.EP)

    def test_safe_methods_still_redirect(self):
        for method in ("GET", "HEAD"):
            with self.subTest(method=method):
                r = self._open("/fr_FR" + self.EP, method)
                self.assertEqual(r.status_code, 301)
                self.assertEqual(self._loc(r), "/fr" + self.EP)
