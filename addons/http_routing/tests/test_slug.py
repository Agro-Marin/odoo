# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import Mock, patch

import werkzeug.routing

from odoo.exceptions import AccessError, MissingError
from odoo.tests import TransactionCase, tagged

from .common import MockRequest
from odoo.addons.http_routing.models.ir_http import ModelConverter


@tagged("-at_install", "post_install")
class TestSlug(TransactionCase):
    """Characterization tests for the slug/unslug helpers on ``ir.http``.

    They back every frontend URL, and the behaviour they encode -- the
    ``name-id`` grammar, negative ids carved out by the slug regex, id ``0``,
    unicode -- is easy to break during a refactor.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrHttp = cls.env["ir.http"]

    # ------------------------------------------------------------------
    # _slug
    # ------------------------------------------------------------------

    def test_slug_from_name_id_tuple(self):
        self.assertEqual(self.IrHttp._slug((14, "My Phone")), "my-phone-14")

    def test_slug_unicode_is_transliterated(self):
        # NFKD strips combining accents (é -> e) but keeps non-latin word
        # chars such as CJK (see ir.http._slugify_one).
        self.assertEqual(self.IrHttp._slug((3, "Café Déjà")), "cafe-deja-3")
        self.assertEqual(self.IrHttp._slug((5, "你好 world")), "你好-world-5")

    def test_slug_nameless_falls_back_to_id(self):
        # A record whose display_name slugifies to nothing => bare id
        self.assertEqual(self.IrHttp._slug((7, "!@#$")), "7")
        self.assertEqual(self.IrHttp._slug((7, "")), "7")

    def test_slug_rejects_a_multi_record_set(self):
        # ``BaseModel.id`` answers ``_ids[0]`` for a multi-record set, so this
        # used to return a URL for whichever record came first -- a link to the
        # wrong page, silently. ``website``'s override reads ``seo_name`` and
        # does raise, so the same mistake was loud or silent depending on which
        # addons happened to be installed.
        langs = self.env["res.lang"].with_context(active_test=False).search([], limit=2)
        self.assertEqual(len(langs), 2, "fixture needs two languages")
        with self.assertRaises(ValueError):
            self.IrHttp._slug(langs)

    def test_slug_accepts_a_singleton(self):
        lang = self.env.ref("base.lang_en")
        self.assertEqual(
            self.IrHttp._slug(lang), self.IrHttp._slug((lang.id, lang.display_name))
        )

    def test_slug_zero_id_raises(self):
        # id 0 is treated as "non-existent record" and must be rejected loudly
        with self.assertRaises(ValueError):
            self.IrHttp._slug((0, "whatever"))

    def test_slug_roundtrips_with_unslug(self):
        for rec_id, name in [(1, "hello"), (42, "My Super Blog"), (999, "x")]:
            slug = self.IrHttp._slug((rec_id, name))
            self.assertEqual(self.IrHttp._unslug(slug)[1], rec_id)

    # ------------------------------------------------------------------
    # _unslug
    # ------------------------------------------------------------------

    def test_unslug_plain_id(self):
        self.assertEqual(self.IrHttp._unslug("1"), (None, 1))

    def test_unslug_name_and_id(self):
        self.assertEqual(self.IrHttp._unslug("my-super-blog-1"), ("my-super-blog", 1))

    def test_unslug_short_name(self):
        # 1-2 char names are allowed by the grammar
        self.assertEqual(self.IrHttp._unslug("a-1"), ("a", 1))
        self.assertEqual(self.IrHttp._unslug("ab-1"), ("ab", 1))

    def test_unslug_negative_id(self):
        # The '-?' in the id sub-pattern lets a trailing '-N' read as a negative
        # id; ModelConverter.to_python() relies on this to fall back to abs().
        self.assertEqual(self.IrHttp._unslug("foo--5"), ("foo", -5))
        self.assertEqual(self.IrHttp._unslug("-1"), (None, -1))

    def test_unslug_stops_at_segment_boundary(self):
        for tail in ("/", "#frag", "?a=b"):
            self.assertEqual(self.IrHttp._unslug("1" + tail), (None, 1))

    def test_unslug_no_id_returns_none_none(self):
        self.assertEqual(self.IrHttp._unslug("x"), (None, None))
        self.assertEqual(self.IrHttp._unslug(""), (None, None))

    # ------------------------------------------------------------------
    # _unslug_url
    # ------------------------------------------------------------------

    def test_unslug_url_reduces_last_segment(self):
        self.assertEqual(self.IrHttp._unslug_url("/blog/my-super-blog-1"), "/blog/1")

    def test_unslug_url_already_bare(self):
        self.assertEqual(self.IrHttp._unslug_url("/blog/1"), "/blog/1")

    def test_unslug_url_no_id_unchanged(self):
        self.assertEqual(self.IrHttp._unslug_url("/blog/about"), "/blog/about")
        self.assertEqual(self.IrHttp._unslug_url("/"), "/")
        self.assertEqual(self.IrHttp._unslug_url(""), "")

    def test_unslug_url_only_touches_last_segment(self):
        self.assertEqual(self.IrHttp._unslug_url("/a/b-2/c-5"), "/a/b-2/5")

    def test_unslug_url_keeps_query_and_fragment(self):
        # _unslug() accepts "?" and "#" as segment terminators, so the raw last
        # split("/") chunk unslugs fine -- but replacing that whole chunk with
        # the bare id used to take the query string/fragment down with it
        # ("/blog/my-blog-1?page=2" -> "/blog/1").
        self.assertEqual(
            self.IrHttp._unslug_url("/blog/my-blog-1?page=2"), "/blog/1?page=2"
        )
        self.assertEqual(
            self.IrHttp._unslug_url("/blog/my-blog-1#comments"), "/blog/1#comments"
        )
        self.assertEqual(
            self.IrHttp._unslug_url("/blog/my-blog-1?a=b#c"), "/blog/1?a=b#c"
        )
        # a "#" inside the query string must not be mistaken for the fragment
        # start of a *later* "?"
        self.assertEqual(self.IrHttp._unslug_url("/blog/x-1#f?a=b"), "/blog/1#f?a=b")

    def test_unslug_url_keeps_a_trailing_slash(self):
        # A trailing slash makes the last split("/") chunk empty, which unslugs
        # to nothing, so the URL came back verbatim: the two spellings of one
        # page compared unequal through ``_unslug_url``, which is exactly the
        # difference it exists to erase (``website.menu`` uses it to decide
        # which menu entry is active).
        self.assertEqual(self.IrHttp._unslug_url("/blog/my-blog-1/"), "/blog/1/")
        self.assertEqual(
            self.IrHttp._unslug_url("/blog/my-blog-1/?p=2"), "/blog/1/?p=2"
        )
        self.assertEqual(self.IrHttp._unslug_url("/blog/about/"), "/blog/about/")
        # the two spellings now agree once the slug is reduced
        self.assertEqual(
            self.IrHttp._unslug_url("/blog/my-blog-1/").rstrip("/"),
            self.IrHttp._unslug_url("/blog/my-blog-1"),
        )

    def test_unslug_url_no_id_keeps_url_verbatim(self):
        self.assertEqual(
            self.IrHttp._unslug_url("/blog/about?page=2"), "/blog/about?page=2"
        )

    # NOTE: get_nearest_lang() is covered in test_lang.TestNearestLang.


@tagged("-at_install", "post_install")
class TestModelConverter(TransactionCase):
    """``http_routing.ModelConverter`` is what turns a "<name>-<id>" path
    segment into a record on every frontend route.
    """

    def _converter(self, model="res.lang"):
        url_map = werkzeug.routing.Map(converters={"model": ModelConverter})
        return ModelConverter(url_map, model=model)

    def test_id_zero_does_not_match(self):
        # "0" is the one id the slug grammar accepts that can never name a
        # record, and every downstream guard let it through: the ORM's
        # ``check_access`` filters ``_ids`` on truthiness, so "/<model>/0" got
        # neither MissingError nor AccessError, and then died in
        # ``_pre_dispatch`` where ``_slug`` refuses to *produce* a 0-id slug --
        # an unauthenticated 500 on every frontend ``<model(...)>`` route.
        #
        # ``ValidationError`` is werkzeug's "this rule does not match", which is
        # what turns it into the 404 "/<model>/999999" already gave.
        with MockRequest(self.env, mock_router=False):
            with self.assertRaises(werkzeug.routing.ValidationError):
                self._converter().to_python("0")
            with self.assertRaises(werkzeug.routing.ValidationError):
                self._converter().to_python("egg-0")

    def test_a_real_id_still_matches(self):
        lang = self.env.ref("base.lang_en")
        with MockRequest(self.env, mock_router=False):
            record = self._converter().to_python(str(lang.id))
            self.assertEqual(record.id, lang.id)
            # the raw segment rides along for website's slug_matching to_url
            self.assertEqual(record.env.context.get("_converter_value"), str(lang.id))

    def test_canonical_redirect_survives_an_unbuildable_url(self):
        # ``_pre_dispatch`` rebuilds the canonical (slugged) URL to 301 towards
        # it. ``rule.build`` runs every converter's ``to_url``, i.e. arbitrary
        # code reading live records: ``_slug`` raises ValueError/MissingError,
        # ``<any(...)>`` raises ValueError. None of those is werkzeug's
        # ValidationError, so none was swallowed and none was caught -- the
        # cosmetic redirect took the whole page down with a 500. (The
        # ``build() is None`` check that was supposed to cover this could never
        # fire: ``Rule.build`` answers None, not ``(_, None)``, so unpacking it
        # raised TypeError first.)
        rule = werkzeug.routing.Rule("/egg/<int:x>", endpoint=Mock(routing={}))
        werkzeug.routing.Map([rule])
        builds = [
            ("ValueError", Mock(side_effect=ValueError("nope"))),
            ("ValidationError", Mock(side_effect=werkzeug.routing.ValidationError())),
            # werkzeug's own way of saying the same thing
            ("None", Mock(return_value=None)),
        ]
        for label, build in builds:
            with self.subTest(build=label):
                with (
                    MockRequest(self.env, path="/egg/1", mock_router=False) as req,
                    patch.object(rule, "build", build),
                    self.assertLogs(
                        "odoo.addons.http_routing.models.ir_http", level="WARNING"
                    ),
                ):
                    req.redirect_query = Mock(
                        side_effect=AssertionError("must not redirect")
                    )
                    # must return normally: the page is served un-slugged
                    self.registry["ir.http"]._pre_dispatch(rule, {"x": 1})

    def test_canonical_redirect_still_reports_a_vanished_record(self):
        # The counterpart of the guard above: a record that is gone or
        # unreadable must keep 404ing. ``_slug`` reads ``display_name``, so
        # MissingError/AccessError out of ``rule.build`` mean exactly that --
        # and for a model without record rules they are the *only* signal,
        # because the ORM's ``check_access`` runs ``ir.rule`` against the id
        # without ever checking that it exists. Swallowing them (a blanket
        # ``except Exception`` here) served a 200 for a phantom record.
        rule = werkzeug.routing.Rule("/egg/<int:x>", endpoint=Mock(routing={}))
        werkzeug.routing.Map([rule])
        for exception in (MissingError("gone"), AccessError("nope")):
            with self.subTest(exception=type(exception).__name__):
                with (
                    MockRequest(self.env, path="/egg/1", mock_router=False),
                    patch.object(rule, "build", Mock(side_effect=exception)),
                    self.assertRaises(type(exception)),
                ):
                    self.registry["ir.http"]._pre_dispatch(rule, {"x": 1})

    def test_negative_id_still_falls_back_to_abs(self):
        # The '-?' in the id sub-pattern lets "foo--5" read as id -5; a record
        # named "foo-" followed by id 5 is the likelier reading, so an id that
        # does not exist is retried as its absolute value.
        lang = self.env.ref("base.lang_en")
        with MockRequest(self.env, mock_router=False):
            record = self._converter().to_python("egg--%s" % lang.id)
            self.assertEqual(record.id, lang.id)
