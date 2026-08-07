import unittest

from odoo.tools.translate import get_translated_module


class TestGetTranslatedModuleFrameWalk(unittest.TestCase):
    def test_over_large_frame_count_falls_back_to_base(self):
        self.assertEqual(get_translated_module(9999), "base")

    def test_none_frame_falls_back_to_base(self):
        self.assertEqual(get_translated_module(None), "base")

    def test_odoo_addons_dotted_name_resolves_module(self):
        self.assertEqual(
            get_translated_module("odoo.addons.sale.models.sale_order"), "sale"
        )

    def test_plain_module_name_passthrough(self):
        self.assertEqual(get_translated_module("my_module"), "my_module")

    def test_non_addons_dotted_name_is_base(self):
        self.assertEqual(get_translated_module("some.other.package"), "base")

    def test_reasonable_int_does_not_raise(self):
        self.assertIsInstance(get_translated_module(1), str)


if __name__ == "__main__":
    unittest.main()
