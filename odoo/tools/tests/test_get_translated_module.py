"""``get_translated_module`` must degrade to "base" when asked for a frame that
does not exist, instead of crashing.

The int form documents ``arg`` as "number of frames to go back to the caller".
Walking past the top of the stack set the local ``frame`` to None and the next
``frame.f_back`` raised ``AttributeError`` -- which defeated the function's own
``if not frame: return "base"`` fallback (dead code, since the loop crashed
first).
"""

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
