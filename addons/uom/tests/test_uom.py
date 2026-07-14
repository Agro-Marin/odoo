# Part of Odoo. See LICENSE file for full copyright and licensing details.

from psycopg import IntegrityError

from odoo.exceptions import UserError
from odoo.tools import mute_logger

from odoo.addons.uom.tests.common import UomCommon


class TestUom(UomCommon):

    def test_10_conversion(self):
        qty = self.uom_gram._compute_quantity(1020000, self.uom_ton)
        self.assertEqual(qty, 1.02, "Converted quantity does not correspond.")

        price = self.uom_gram._compute_price(2, self.uom_ton)
        self.assertEqual(price, 2000000.0, "Converted price does not correspond.")

        # If the conversion factor for Dozens (1/12) is not stored with sufficient precision,
        # the conversion of 1 Dozen into Units will give e.g. 12.00000000000047 Units
        # and the Unit rounding will round that up to 13.
        # This is a partial regression test for rev. 311c77bb, which is further improved
        # by rev. fa2f7b86.
        qty = self.uom_dozen._compute_quantity(1, self.uom_unit)
        self.assertEqual(qty, 12.0, "Converted quantity does not correspond.")

        # Regression test for side-effect of commit 311c77bb - converting 1234 Grams
        # into Kilograms should work even if grams are rounded to 1.
        qty = self.uom_gram._compute_quantity(1234, self.uom_kgm)
        self.assertEqual(qty, 1.24, "Converted quantity does not correspond.")

    def test_20_rounding(self):
        product_uom_id = self.env['uom.uom'].create({
            'name': 'Score',
            'relative_factor': 20,
            'relative_uom_id': self.uom_unit.id,
        })
        self.env['decimal.precision'].search([('name', '=', 'Product Unit')]).digits = 0

        qty = self.uom_unit._compute_quantity(2, product_uom_id)
        self.assertEqual(qty, 1, "Converted quantity should be rounded up.")

    def test_30_quantity(self):
        """ _check_qty rounds the available quantity of a product. To prevent rounding issue,
        there should be no rounding if the product uom is the same as the package uom.
        """
        uom = self.uom_unit
        quantity = 22.43
        rounding_method = 'DOWN'

        result = self.uom_unit._check_qty(quantity, uom, rounding_method)

        self.assertEqual(result, quantity, 'Quantity should not be rounded.')

    def test_check_qty_multiples(self):
        """_check_qty must round to exact multiples of the packaging, without
        distortion from pre-rounding the packaging factor (12 Units used to
        come back as 11.97 because 1/12 was rounded to 0.09 first)."""
        # 12 dozens = 144 units: already a whole multiple of one Unit
        self.assertEqual(self.uom_unit._check_qty(12, self.uom_dozen), 12.0)
        self.assertEqual(self.uom_unit._check_qty(11, self.uom_dozen, 'DOWN'), 11.0)
        # 1.04 dozen = 12.48 units -> 12 units (DOWN) / 13 units (UP)
        self.assertEqual(self.uom_unit._check_qty(1.04, self.uom_dozen, 'DOWN'), 1.0)
        self.assertEqual(self.uom_unit._check_qty(1.04, self.uom_dozen, 'UP'), 1.08)
        # packaging expressed in the product uom (stock reservation direction)
        pack_6 = self.quick_ref('uom.product_uom_pack_6')
        self.assertEqual(pack_6._check_qty(14, self.uom_unit, 'DOWN'), 12.0)
        self.assertEqual(pack_6._check_qty(14, self.uom_unit, 'UP'), 18.0)

    def test_minute_hour_roundtrip(self):
        """The Minutes factor must be exactly 1/60: with the historical
        0.0166667, 60 minutes converted (rounding UP) to 1.01 hours."""
        uom_minute = self.quick_ref('uom.product_uom_minute')
        self.assertEqual(uom_minute._compute_quantity(60, self.uom_hour), 1.0)
        self.assertEqual(self.uom_hour._compute_quantity(1, uom_minute), 60.0)

    def test_cross_reference_conversion(self):
        """Converting between units without a common reference unit raises,
        unless the caller opts out with raise_if_failure=False."""
        self.assertFalse(self.uom_gram._has_common_reference(self.uom_hour))
        self.assertTrue(self.uom_gram._has_common_reference(self.uom_ton))
        self.assertTrue(self.uom_gram._has_common_reference(self.uom_gram))

        with self.assertRaises(UserError):
            self.uom_gram._compute_quantity(1000, self.uom_hour)
        self.assertEqual(
            self.uom_gram._compute_quantity(1000, self.uom_hour, raise_if_failure=False),
            1000,
            "Failed conversions must return the initial quantity",
        )

    def test_conversion_degenerate_recordsets(self):
        empty_uom = self.env['uom.uom']
        self.assertEqual(empty_uom._compute_quantity(5.0, self.uom_gram), 5.0)
        self.assertEqual(self.uom_gram._compute_quantity(5.0, empty_uom), 5.0)
        self.assertEqual(self.uom_gram._compute_quantity(0.0, self.uom_ton), 0.0)

    def test_compute_price(self):
        self.assertEqual(self.uom_gram._compute_price(5.0, self.uom_gram), 5.0)
        self.assertEqual(self.uom_gram._compute_price(0.0, self.uom_ton), 0.0)
        self.assertEqual(self.uom_ton._compute_price(2000000.0, self.uom_gram), 2.0)
        self.assertEqual(self.uom_gram._compute_price(5.0, self.env['uom.uom']), 5.0)

    def test_factor_must_be_strictly_positive(self):
        for factor in (0, -5):
            with self.subTest(factor=factor), \
                    mute_logger('odoo.db'), \
                    self.assertRaises(IntegrityError), \
                    self.cr.savepoint():
                self.env['uom.uom'].create({
                    'name': 'Broken',
                    'relative_factor': factor,
                    'relative_uom_id': self.uom_unit.id,
                })

    def test_reference_uom_must_have_factor_one(self):
        with self.assertRaises(UserError):
            self.env['uom.uom'].create({
                'name': 'Rootless',
                'relative_factor': 2.0,
            })

    def test_recursive_reference_rejected(self):
        pack_6 = self.quick_ref('uom.product_uom_pack_6')
        with self.assertRaises(UserError), self.cr.savepoint():
            self.uom_unit.relative_uom_id = pack_6

    def test_protected_uom_unlink(self):
        with self.assertRaises(UserError):
            self.uom_kgm.unlink()

    def test_sequence_defaults(self):
        uom = self.env['uom.uom'].create({
            'name': 'Triple',
            'relative_factor': 3,
            'relative_uom_id': self.uom_unit.id,
        })
        self.assertEqual(uom.sequence, 300)
        uom.relative_factor = 5
        self.assertEqual(uom.sequence, 300, "An existing sequence must be preserved")
        big = self.env['uom.uom'].create({
            'name': 'Big',
            'relative_factor': 5000,
            'relative_uom_id': self.uom_unit.id,
        })
        self.assertEqual(big.sequence, 1000, "Sequence is capped at 1000")

    def test_factor_chain(self):
        """`factor` is the product of relative factors up to the reference unit
        and follows updates anywhere in the chain."""
        self.assertEqual(self.uom_ton.factor, 1000000.0)
        kiloton = self.env['uom.uom'].create({
            'name': 'Kiloton',
            'relative_factor': 1000,
            'relative_uom_id': self.uom_ton.id,
        })
        self.assertEqual(kiloton.factor, 1e9)
        self.uom_kgm.relative_factor = 500
        self.assertEqual(kiloton.factor, 5e8, "Factor must follow chain updates")
