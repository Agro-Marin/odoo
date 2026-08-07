import unittest

from lxml import etree

from odoo.tools.convert import _eval_xml
from odoo.tools.safe_eval import _UNSAFE_ATTRIBUTES


class _ExplodingEnv(dict):
    context: dict = {}

    def __getitem__(self, key):
        raise AssertionError(f"the name guard let {key!r} through to model resolution")


def _function_node(name: str) -> etree._Element:
    return etree.fromstring(f'<function model="res.partner" name="{name}"/>')


class TestFunctionNameGuard(unittest.TestCase):
    def test_dunder_names_are_refused(self):
        for name in (
            "__getattribute__",
            "__class__",
            "__init__",
            "__dict__",
            "_do__thing",
        ):
            with self.subTest(name=name):
                with self.assertRaises(NameError) as ctx:
                    _eval_xml(None, _function_node(name), _ExplodingEnv())
                self.assertIn(name, str(ctx.exception))

    def test_every_unsafe_attribute_is_refused(self):
        for name in _UNSAFE_ATTRIBUTES:
            with self.subTest(name=name):
                with self.assertRaises(NameError):
                    _eval_xml(None, _function_node(name), _ExplodingEnv())

    def test_a_missing_name_becomes_the_empty_string(self):
        node = etree.fromstring('<function model="res.partner"/>')
        with self.assertRaises(AssertionError):
            _eval_xml(None, node, _ExplodingEnv())

    def test_an_ordinary_name_passes_the_guard(self):
        with self.assertRaises(AssertionError) as ctx:
            _eval_xml(None, _function_node("create"), _ExplodingEnv())
        self.assertIn("res.partner", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
