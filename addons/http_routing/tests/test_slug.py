from unittest.mock import Mock, patch

import werkzeug.routing

from odoo.exceptions import AccessError, MissingError
from odoo.tests import TransactionCase, tagged

from .common import MockRequest
from odoo.addons.http_routing.models.ir_http import ModelConverter


@tagged("-at_install", "post_install")
class TestSlug(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrHttp = cls.env["ir.http"]

    def test_slug_from_name_id_tuple(self):
        self.assertEqual(self.IrHttp._slug((14, "My Phone")), "my-phone-14")

    def test_slug_unicode_is_transliterated(self):
        self.assertEqual(self.IrHttp._slug((3, "Café Déjà")), "cafe-deja-3")
        self.assertEqual(self.IrHttp._slug((5, "你好 world")), "你好-world-5")

    def test_slug_nameless_falls_back_to_id(self):
        self.assertEqual(self.IrHttp._slug((7, "!@#$")), "7")
        self.assertEqual(self.IrHttp._slug((7, "")), "7")

    def test_slug_rejects_a_multi_record_set(self):
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
        with self.assertRaises(ValueError):
            self.IrHttp._slug((0, "whatever"))

    def test_slug_roundtrips_with_unslug(self):
        for rec_id, name in [(1, "hello"), (42, "My Super Blog"), (999, "x")]:
            slug = self.IrHttp._slug((rec_id, name))
            self.assertEqual(self.IrHttp._unslug(slug)[1], rec_id)

    def test_unslug_plain_id(self):
        self.assertEqual(self.IrHttp._unslug("1"), (None, 1))

    def test_unslug_name_and_id(self):
        self.assertEqual(self.IrHttp._unslug("my-super-blog-1"), ("my-super-blog", 1))

    def test_unslug_short_name(self):
        self.assertEqual(self.IrHttp._unslug("a-1"), ("a", 1))
        self.assertEqual(self.IrHttp._unslug("ab-1"), ("ab", 1))

    def test_unslug_negative_id(self):
        self.assertEqual(self.IrHttp._unslug("foo--5"), ("foo", -5))
        self.assertEqual(self.IrHttp._unslug("-1"), (None, -1))

    def test_unslug_stops_at_segment_boundary(self):
        for tail in ("/", "#frag", "?a=b"):
            self.assertEqual(self.IrHttp._unslug("1" + tail), (None, 1))

    def test_unslug_no_id_returns_none_none(self):
        self.assertEqual(self.IrHttp._unslug("x"), (None, None))
        self.assertEqual(self.IrHttp._unslug(""), (None, None))

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
        self.assertEqual(
            self.IrHttp._unslug_url("/blog/my-blog-1?page=2"), "/blog/1?page=2"
        )
        self.assertEqual(
            self.IrHttp._unslug_url("/blog/my-blog-1#comments"), "/blog/1#comments"
        )
        self.assertEqual(
            self.IrHttp._unslug_url("/blog/my-blog-1?a=b#c"), "/blog/1?a=b#c"
        )
        self.assertEqual(self.IrHttp._unslug_url("/blog/x-1#f?a=b"), "/blog/1#f?a=b")

    def test_unslug_url_keeps_a_trailing_slash(self):
        self.assertEqual(self.IrHttp._unslug_url("/blog/my-blog-1/"), "/blog/1/")
        self.assertEqual(
            self.IrHttp._unslug_url("/blog/my-blog-1/?p=2"), "/blog/1/?p=2"
        )
        self.assertEqual(self.IrHttp._unslug_url("/blog/about/"), "/blog/about/")
        self.assertEqual(
            self.IrHttp._unslug_url("/blog/my-blog-1/").rstrip("/"),
            self.IrHttp._unslug_url("/blog/my-blog-1"),
        )

    def test_unslug_url_no_id_keeps_url_verbatim(self):
        self.assertEqual(
            self.IrHttp._unslug_url("/blog/about?page=2"), "/blog/about?page=2"
        )


@tagged("-at_install", "post_install")
class TestModelConverter(TransactionCase):
    def _converter(self, model="res.lang"):
        url_map = werkzeug.routing.Map(converters={"model": ModelConverter})
        return ModelConverter(url_map, model=model)

    def test_id_zero_does_not_match(self):
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
            self.assertEqual(record.env.context.get("_converter_value"), str(lang.id))

    def test_canonical_redirect_survives_an_unbuildable_url(self):
        rule = werkzeug.routing.Rule("/egg/<int:x>", endpoint=Mock(routing={}))
        werkzeug.routing.Map([rule])
        builds = [
            ("ValueError", Mock(side_effect=ValueError("nope"))),
            ("ValidationError", Mock(side_effect=werkzeug.routing.ValidationError())),
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
                    self.registry["ir.http"]._pre_dispatch(rule, {"x": 1})

    def test_canonical_redirect_still_reports_a_vanished_record(self):
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
        lang = self.env.ref("base.lang_en")
        with MockRequest(self.env, mock_router=False):
            record = self._converter().to_python("egg--%s" % lang.id)
            self.assertEqual(record.id, lang.id)
