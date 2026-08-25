"""What ``_check_module`` walks, and what it deliberately does not.

The guard's contract is "no module reachable through plain data". These tests
pin both halves of it: the carriers it must refuse, and the two omissions that
are intentional, so neither half can drift silently.
"""

import collections
import os
import types
import unittest

from odoo.tools.safe_eval import check_values, safe_eval


class TestPlainDataCarriersAreRefused(unittest.TestCase):
    """Every carrier that is plain data must be walked."""

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
        # A mappingproxy is a read-only dict, so it is plain data -- but it is
        # not a dict instance, which is how it used to slip through.
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
    """The two carriers the guard does not walk, and why.

    These assert a *known limit*. A future change that closes one of them should
    replace the assertion, not be surprised by it.
    """

    def test_an_iterator_is_not_walked_and_not_consumed(self):
        # Walking would consume it: the caller's value must survive the check.
        values = [1, 2, 3]
        it = iter(values)
        check_values({"it": it})
        self.assertEqual(list(it), values, "check_values consumed the iterator")

    def test_a_module_behind_an_object_attribute_still_reaches_the_context(self):
        # Walking object attributes would reach recordset attributes and trigger
        # database reads, so the guard stops short.
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
