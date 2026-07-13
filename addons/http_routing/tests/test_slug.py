# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestSlug(TransactionCase):
    """Characterization tests for the slug/unslug helpers on ``ir.http``.

    These helpers back every frontend URL (blog posts, products, events, ...)
    yet lived without direct unit coverage; the behaviour they encode -- the
    ``name-id`` grammar, negative ids carved out by the slug regex, id ``0``,
    unicode -- is easy to break during a refactor. Pin it down here.
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

    # NOTE: get_nearest_lang() is covered in test_lang.py. In this module its
    # base implementation is a pure function of the active languages (no
    # ``request``), so it is unit-testable here; website's override (which reads
    # ``request``) is exercised by website's test_lang_url.
