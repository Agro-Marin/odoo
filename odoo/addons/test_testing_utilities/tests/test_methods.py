import itertools
from unittest import TestCase, mock

import psycopg

from odoo.db import BaseCursor
from odoo.exceptions import AccessError
from odoo.tests import common
from odoo.tools import mute_logger


class CustomError(Exception): ...


class TestBasic(common.TransactionCase):
    def test_assertRecordValues(self):
        X1 = {"f1": "X", "f2": 1}
        Y2 = {"f1": "Y", "f2": 2}
        Y3 = {"f1": "Y", "f2": 3}
        records = self.env["test_testing_utilities.a"].create([X1, Y2])

        self.assertRecordValues(records, [X1, Y2])

        with self.assertRaises(AssertionError):
            self.assertRecordValues(records, [Y2, X1])

        with self.assertRaises(AssertionError):
            self.assertRecordValues(records, [X1])
        with self.assertRaises(AssertionError):
            self.assertRecordValues(records, [X1, Y2, Y3])

        with self.assertRaises(AssertionError):
            self.assertRecordValues(records, [X1, Y3])
        with self.assertRaises(AssertionError):
            self.assertRecordValues(records, [Y3, X1])

    def test_assertRecordValues_floats(self):
        r = self.env["test_testing_utilities.onchange_line"].create(
            {
                "dummy": 42,
            }
        )

        self.assertRecordValues(r, [{"dummy": 42}])

    def test_assertRecordValues_float_formatting(self):
        self.patch(self, "maxDiff", 80 * 8)

        Records = self.env["test_testing_utilities.wide"]
        names = sorted(Records._fields.keys() - {"id", "display_name"})

        d = {n: float(k) for k, n in enumerate(names)}

        values = [{**d, "name": float(i), "price_total": float(i)} for i in range(200)]
        values[63]["quantity"] = False
        records = Records.create(values)
        values[63]["price_total"] = 42.0

        with self.assertRaises(AssertionError) as cm:
            self.assertRecordValues(records, values)

        self.maxDiff = None
        self.assertEqual(
            str(cm.exception),
            """\
Lists differ: [{'ac[24051 chars]al': 42.0, 'price_unit': 11.0, 'product_id': 1[51872 chars]8.0}] != [{'ac[24051 chars]al': 63.0, 'price_unit': 11.0, 'product_id': 1[51872 chars]8.0}]

First differing element 63:
{'acc[193 chars]al': 42.0, 'price_unit': 11.0, 'product_id': 1[127 chars]18.0}
{'acc[193 chars]al': 63.0, 'price_unit': 11.0, 'product_id': 1[127 chars]18.0}

--- expected
+++ records
@@ -1205,7 +1205,7 @@
   'name': 63.0,
   'partner_id': 8.0,
   'price_subtotal': 9.0,
-  'price_total': 42.0,
+  'price_total': 63.0,
   'price_unit': 11.0,
   'product_id': 12.0,
   'product_uom_id': 13.0,
""",
        )

        vs = {
            k: v
            for k, v in values[63].items()
            if k in ("discount", "price_subtotal", "price_total", "quantity")
        }
        with self.assertRaises(AssertionError) as cm:
            self.assertRecordValues(records[63], [vs])
        self.assertEqual(
            str(cm.exception),
            """\
Lists differ: [{'discount': 6.0, 'price_subtotal': 9.0, 'price_total': 42.0, 'quantity': 0.0}] != [{'discount': 6.0, 'price_subtotal': 9.0, 'price_total': 63.0, 'quantity': 0.0}]

First differing element 0:
{'discount': 6.0, 'price_subtotal': 9.0, 'price_total': 42.0, 'quantity': 0.0}
{'discount': 6.0, 'price_subtotal': 9.0, 'price_total': 63.0, 'quantity': 0.0}

- [{'discount': 6.0, 'price_subtotal': 9.0, 'price_total': 42.0, 'quantity': 0.0}]
?                                                          ^^

+ [{'discount': 6.0, 'price_subtotal': 9.0, 'price_total': 63.0, 'quantity': 0.0}]
?                                                          ^^
""",
        )

    def test_assertRaises_rollbacks(self):
        self.env.cr.execute("SET LOCAL test_testing_utilities.a_flag = ''")
        with self.assertRaises(CustomError):
            self.env.cr.execute("SET LOCAL test_testing_utilities.a_flag = 'yes'")
            raise CustomError

        self.env.cr.execute("SHOW test_testing_utilities.a_flag")
        self.assertEqual(self.env.cr.fetchone(), ("",))

    def test_assertRaises_error_at_setup(self):
        with (
            mock.patch.object(BaseCursor, "flush", side_effect=CustomError),
            TestCase.assertRaises(self, CustomError),
        ):
            with self.assertRaises(CustomError):
                raise NotImplementedError

    def test_assertRaises_error_at_exit(self):
        self.env.cr.execute("SET LOCAL test_testing_utilities.a_flag = ''")
        with mock.patch.object(BaseCursor, "flush", side_effect=[None, CustomError]):
            with self.assertRaises(CustomError):
                self.env.cr.execute("SET LOCAL test_testing_utilities.a_flag = 'yes'")

        self.env.cr.execute("SHOW test_testing_utilities.a_flag")
        self.assertEqual(self.env.cr.fetchone(), ("",))

    @mute_logger("odoo.db")
    def test_assertRaises_clear_recovery(self):

        # The evaluated-once default is the mechanism here: `clear` has to fail
        # on its first call only, so the counter must persist across calls.
        def clear(call_count=itertools.count()):  # noqa: B008  see comment above
            if next(call_count) == 0:
                self.env.cr.execute("select nonsense")

        with (
            mock.patch.object(BaseCursor, "clear", side_effect=clear),
            TestCase.assertRaises(self, psycopg.Error),
        ):
            with self.assertRaises(AccessError):
                raise NotImplementedError

        self.env.cr.execute("select 1")
