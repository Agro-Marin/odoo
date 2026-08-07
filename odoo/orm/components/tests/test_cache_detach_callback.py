import unittest

from odoo.orm.components.cache import FieldCache


class _F:
    def __init__(self, name: str, model_name: str = "m") -> None:
        self.name = name
        self.model_name = model_name

    def __repr__(self) -> str:
        return f"<F {self.model_name}.{self.name}>"


class TestDetachCallback(unittest.TestCase):
    def setUp(self) -> None:
        self.fired = []
        self.cache = FieldCache(on_detach=lambda: self.fired.append(1))
        self.f = _F("a")

    def test_clear_fires(self) -> None:
        self.cache.set_value(self.f, 1, "x")
        self.cache.clear()
        self.assertEqual(len(self.fired), 1)

    def test_invalidate_all_fires(self) -> None:
        self.cache.set_value(self.f, 1, "x")
        self.cache.invalidate_all()
        self.assertEqual(len(self.fired), 1)

    def test_invalidate_all_fires_with_dirty_entries_too(self) -> None:
        g = _F("b")
        self.cache.set_value(self.f, 1, "x")
        self.cache.set_value(g, 1, "y")
        self.cache.mark_dirty(g, [1])
        self.cache.invalidate_all()
        self.assertEqual(len(self.fired), 1)
        self.assertIsNone(self.cache.get_field_data_or_none(self.f))

    def test_invalidate_field_fires_when_it_drops_a_sub_dict(self) -> None:
        key = ("en_US",)
        self.cache.get_field_data(self.f)[key] = {1: "x"}
        self.cache.invalidate_field(self.f, [1])
        self.assertEqual(len(self.fired), 1)
        self.assertNotIn(key, self.cache.get_field_data(self.f))

    def test_invalidate_does_not_fire(self) -> None:
        self.cache.set_value(self.f, 1, "x")
        self.cache.invalidate(self.f, [1], context_dependent=False)
        self.assertEqual(self.fired, [])

    def test_invalidate_whole_field_does_not_fire(self) -> None:
        self.cache.set_value(self.f, 1, "x")
        self.cache.invalidate(self.f, None, context_dependent=False)
        self.assertEqual(self.fired, [])
        self.assertEqual(self.cache.get_field_data(self.f), {})

    def test_context_dependent_invalidate_keeps_the_sub_dict_object(self) -> None:
        key = ("en_US",)
        sub = {1: "x"}
        self.cache.get_field_data(self.f)[key] = sub
        self.cache.invalidate(self.f, None, context_dependent=True)
        self.assertEqual(self.fired, [])
        self.assertIs(self.cache.get_field_data(self.f)[key], sub)
        self.assertEqual(sub, {})

    def test_invalidate_field_without_emptying_does_not_fire(self) -> None:
        key = ("en_US",)
        self.cache.get_field_data(self.f)[key] = {1: "x", 2: "y"}
        self.cache.invalidate_field(self.f, [1])
        self.assertEqual(self.fired, [])

    def test_no_callback_configured_is_a_no_op(self) -> None:
        cache = FieldCache()
        cache.set_value(self.f, 1, "x")
        cache.clear()
        cache.invalidate_all()
        self.assertEqual(cache.get_field_data_or_none(self.f), None)


if __name__ == "__main__":
    unittest.main()
