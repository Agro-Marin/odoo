import collections
import os
import types
import unittest

from odoo.tools.safe_eval import check_values, safe_eval


class TestPlainDataCarriersAreRefused(unittest.TestCase):
    def test_a_module_passed_directly(self):
        with self.assertRaises(TypeError):
            check_values({"m": os})

    def test_a_dict_value(self):
        with self.assertRaises(TypeError):
            check_values({"d": {"k": os}})

    def test_a_dict_key(self):
        with self.assertRaises(TypeError):
            check_values({"d": {os: 1}})

    def test_a_list(self):
        with self.assertRaises(TypeError):
            check_values({"l": [os]})

    def test_a_deeply_nested_mix(self):
        with self.assertRaises(TypeError):
            check_values({"l": [[{"x": (os,)}]]})

    def test_a_mappingproxy_value(self):
        self.assertFalse(isinstance(types.MappingProxyType({}), dict))
        with self.assertRaises(TypeError):
            check_values({"mp": types.MappingProxyType({"m": os})})

    def test_a_mappingproxy_key(self):
        with self.assertRaises(TypeError):
            check_values({"mp": types.MappingProxyType({os: 1})})

    def test_a_mappingproxy_nested_in_a_dict(self):
        with self.assertRaises(TypeError):
            check_values({"d": {"mp": types.MappingProxyType({"m": os})}})

    def test_a_deque(self):
        with self.assertRaises(TypeError):
            check_values({"dq": collections.deque([os])})


class TestTheOmissionsAreIntentional(unittest.TestCase):
    def test_an_iterator_is_not_walked_and_not_consumed(self):
        values = [1, 2, 3]
        it = iter(values)
        check_values({"it": it})
        self.assertEqual(list(it), values, "check_values consumed the iterator")

    def test_a_module_behind_an_object_attribute_still_reaches_the_context(self):
        ctx = {"ns": types.SimpleNamespace(m=os)}
        check_values(ctx)
        self.assertEqual(safe_eval("ns.m.sep", ctx), os.sep)

    def test_a_module_behind_a_class_attribute_still_reaches_the_context(self):
        ctx = {"C": type("C", (), {"m": os})}
        check_values(ctx)
        self.assertEqual(safe_eval("C.m.sep", ctx), os.sep)


class TestLegitimateContextsAreUnaffected(unittest.TestCase):
    def test_the_wrapped_modules_this_package_exposes_are_accepted(self):
        from odoo.tools import safe_eval as se

        wrapped = {n: getattr(se, n) for n in ("json", "time", "datetime", "pytz")}
        self.assertEqual(check_values(dict(wrapped)), wrapped)

    def test_ordinary_data_passes(self):
        values = {
            "a": 1,
            "b": [1, 2],
            "c": {"d": "x"},
            "e": types.MappingProxyType({"f": 2}),
        }
        self.assertEqual(check_values(values), values)

    def test_an_empty_or_absent_mapping_is_returned_as_is(self):
        self.assertIsNone(check_values(None))
        self.assertEqual(check_values({}), {})
