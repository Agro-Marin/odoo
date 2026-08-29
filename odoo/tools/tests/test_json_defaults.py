"""json_default and orjson_default answer to one conversion table.

They used to carry a copy each and had drifted: only orjson's knew about
dataclasses, so the same object serialised as {"x": 1} through one encoder and
"P(x=1)" through the other.  What legitimately differs between them is
*recursion* -- the stdlib encoder re-enters `default` on a value it still cannot
serialise, orjson calls it once -- not policy.
"""

import dataclasses
import datetime
import unittest

from odoo.libs.collections import ReadonlyDict
from odoo.libs.func import lazy
from odoo.tools.json import json_default, orjson_default


@dataclasses.dataclass
class _Point:
    x: int = 1
    y: int = 2


CASES = {
    "datetime": datetime.datetime(2026, 8, 29, 12, 0, 0),
    "date": datetime.date(2026, 8, 29),
    "bytes": b"hi",
    "readonly_dict": ReadonlyDict({"a": 1}),
    "dataclass": _Point(),
}


class TestConversionPolicyIsShared(unittest.TestCase):
    def test_both_defaults_convert_every_case_identically(self):
        for name, value in CASES.items():
            with self.subTest(case=name):
                self.assertEqual(json_default(value), orjson_default(value))

    def test_a_dataclass_becomes_a_dict_not_its_repr(self):
        # The drift that motivated this: json_default fell through to str().
        for fn in (json_default, orjson_default):
            with self.subTest(default=fn.__name__):
                self.assertEqual(fn(_Point()), {"x": 1, "y": 2})

    def test_a_lazy_is_unwrapped_by_both(self):
        for name, value in CASES.items():
            with self.subTest(case=name):
                wrapped = lazy(lambda v=value: v)
                # orjson gets no second pass, so it must convert in one step
                self.assertEqual(orjson_default(wrapped), orjson_default(value))
                # the stdlib encoder re-enters default, so one unwrap suffices
                self.assertEqual(
                    json_default(json_default(wrapped)), json_default(value)
                )

    def test_a_lazy_over_a_native_value_is_returned_as_is(self):
        for native in (5, "s", 1.5, True, None, [1], {"a": 1}):
            with self.subTest(value=native):
                self.assertEqual(orjson_default(lazy(lambda v=native: v)), native)

    def test_an_unknown_object_still_falls_back_to_str(self):
        class Opaque:
            def __repr__(self):
                return "<opaque>"

        self.assertEqual(json_default(Opaque()), "<opaque>")
        self.assertEqual(orjson_default(Opaque()), "<opaque>")


if __name__ == "__main__":
    unittest.main()
