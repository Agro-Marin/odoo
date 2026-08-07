import unittest

from odoo.tools.cache import _render_signature, ormcache


class _Opaque:
    def __repr__(self):
        return "<opaque object at 0xdeadbeef>"


SENTINEL = _Opaque()


class _FakeModel:
    _name = "fake.model"


class TestRenderSignature(unittest.TestCase):
    def test_plain_params(self):
        def m(self, a, b):
            pass

        self.assertEqual(_render_signature(m), ("self, a, b", {}))

    def test_literal_default_is_bound_not_inlined(self):
        def m(self, a, mode="read"):
            pass

        rendered, globs = _render_signature(m)
        self.assertEqual(rendered, "self, a, mode=__ormcache_default_2")
        self.assertEqual(globs, {"__ormcache_default_2": "read"})

    def test_non_literal_default_does_not_raise(self):
        def m(self, a, flag=SENTINEL):
            pass

        rendered, globs = _render_signature(m)
        self.assertIs(globs["__ormcache_default_2"], SENTINEL)
        self.assertNotIn("opaque", rendered)

    def test_var_positional_and_keyword(self):
        def m(self, *args, **kwargs):
            pass

        self.assertEqual(_render_signature(m), ("self, *args, **kwargs", {}))

    def test_keyword_only_marker_is_emitted(self):
        def m(self, a, *, b):
            pass

        rendered, _ = _render_signature(m)
        self.assertEqual(rendered, "self, a, *, b")

    def test_positional_only_marker_is_emitted(self):
        def m(self, a, /, b):
            pass

        rendered, _ = _render_signature(m)
        self.assertEqual(rendered, "self, a, /, b")

    def test_trailing_positional_only_marker(self):
        def m(self, a, /):
            pass

        rendered, _ = _render_signature(m)
        self.assertEqual(rendered, "self, a, /")

    def test_var_positional_then_keyword_only_emits_no_extra_star(self):
        def m(self, *args, b=1):
            pass

        rendered, _ = _render_signature(m)
        self.assertEqual(rendered, "self, *args, b=__ormcache_default_2")


class TestOrmcacheDeterminesKey(unittest.TestCase):
    def _key_of(self, method, *args, **kwargs):
        deco = ormcache("a")
        deco.method = method
        deco.determine_key()
        return deco.key(*args, **kwargs)

    def test_non_literal_default_decorates_without_syntaxerror(self):
        def m(self, a, flag=SENTINEL):
            pass

        key = self._key_of(m, _FakeModel(), 7)
        self.assertEqual(key, ("fake.model", m, 7))

    def test_literal_default_still_works(self):
        def m(self, a, mode="read"):
            pass

        self.assertEqual(self._key_of(m, _FakeModel(), 7), ("fake.model", m, 7))

    def test_key_varies_with_the_keyed_argument(self):
        def m(self, a, mode="read"):
            pass

        model = _FakeModel()
        self.assertNotEqual(self._key_of(m, model, 1), self._key_of(m, model, 2))

    def test_keyword_only_method_is_callable_by_keyword(self):
        def m(self, a, *, mode="read"):
            pass

        self.assertEqual(
            self._key_of(m, _FakeModel(), 7, mode="write"), ("fake.model", m, 7)
        )

    def test_first_parameter_need_not_be_named_self(self):
        def m(records, a):
            pass

        self.assertEqual(self._key_of(m, _FakeModel(), 7), ("fake.model", m, 7))


if __name__ == "__main__":
    unittest.main()
