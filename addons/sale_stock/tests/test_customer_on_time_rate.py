"""Tests for the customer on-time delivery rate on partners."""

from odoo.tests import tagged

from .common import TestSaleStockCommon


@tagged("post_install", "-at_install")
class TestCustomerOnTimeRate(TestSaleStockCommon):
    """No-data sentinel of the on-time rate.

    The rate-value tests (on-time, late, weighted mix, lookback window) are
    written but NOT landed: the KPI is blind while its domain filters on the
    removed 'sale' order state (see the bug task on the stale state rename).
    They go in with that fix, not before.
    """

    def test_no_data_yields_negative_sentinel(self):
        """A partner without delivered sale lines reports -1, not 0.

        The sentinel matters: 0 would read as "never delivers on time",
        which is a very different statement from "no deliveries yet".
        """
        partner = self.env["res.partner"].create({"name": "No history partner"})
        self.assertEqual(partner.customer_on_time_rate, -1)
