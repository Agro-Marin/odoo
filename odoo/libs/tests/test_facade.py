import unittest

from odoo.libs.facade import Proxy, ProxyAttr, ProxyFunc


class Wrapped:
    def __init__(self):
        self.plain = 10
        self.raw = "5"
        self.maybe_none = None

    def get_value(self):
        return self.plain

    def instance_echo(self, x):
        return x

    @staticmethod
    def static_add(a, b):
        return a + b

    @classmethod
    def cls_name(cls):
        return cls.__name__


class MyProxy(Proxy):
    _wrapped__ = Wrapped

    plain = ProxyAttr()
    raw = ProxyAttr(cast=int)
    maybe_none = ProxyAttr(cast=int)

    get_value = ProxyFunc()
    instance_echo = ProxyFunc(cast=None)
    static_add = ProxyFunc(cast=str)
    cls_name = ProxyFunc()


class TestProxyAttr(unittest.TestCase):
    def setUp(self):
        self.wrapped = Wrapped()
        self.proxy = MyProxy(self.wrapped)

    def test_uncast_get_and_set(self):
        self.assertEqual(self.proxy.plain, 10)
        self.proxy.plain = 20
        self.assertEqual(self.wrapped.plain, 20)

    def test_cast_applies_to_a_non_none_value(self):
        self.assertEqual(self.proxy.raw, 5)
        self.assertIsInstance(self.proxy.raw, int)

    def test_cast_is_skipped_for_none(self):
        self.assertIsNone(self.proxy.maybe_none)

    def test_set_writes_through_to_the_wrapped_instance(self):
        self.proxy.raw = "9"
        self.assertEqual(self.wrapped.raw, "9")


class TestProxyFuncDispatch(unittest.TestCase):
    def setUp(self):
        self.wrapped = Wrapped()
        self.proxy = MyProxy(self.wrapped)

    def test_instance_method_dispatches_to_the_wrapped_instance(self):
        self.assertEqual(self.proxy.get_value(), 10)

    def test_cast_none_discards_the_result(self):
        self.assertIsNone(self.proxy.instance_echo(42))

    def test_staticmethod_dispatch_applies_cast(self):
        result = self.proxy.static_add(3, 4)
        self.assertEqual(result, "7")
        self.assertIsInstance(result, str)

    def test_classmethod_dispatch_resolves_against_the_wrapped_class(self):
        self.assertEqual(self.proxy.cls_name(), "Wrapped")


class TestProxyClassIdentity(unittest.TestCase):
    def test_isinstance_follows_the_wrapped_class(self):
        proxy = MyProxy(Wrapped())
        self.assertIsInstance(proxy, Wrapped)

    def test_repr_and_str_default_to_the_wrapped_instance(self):
        wrapped = Wrapped()
        proxy = MyProxy(wrapped)
        self.assertEqual(repr(proxy), repr(wrapped))
        self.assertEqual(str(proxy), str(wrapped))


if __name__ == "__main__":
    unittest.main()
